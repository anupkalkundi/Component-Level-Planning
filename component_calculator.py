import streamlit as st
import pandas as pd
import re
from decimal import Decimal
from psycopg2.extras import execute_values


class FormulaError(Exception):
    pass


VARIABLE_ALIASES = {
    "opening_height": "opening_length",
    "opening_l": "opening_length",
    "opening_w": "opening_width",
    "height_opening": "opening_length",
    "width_opening": "opening_width",
    "clearance": "vertical_clearance",
    "clr": "vertical_clearance",
    "v_clearance": "vertical_clearance",
    "h_clearance": "horizontal_clearance",
    "extra_l": "architrave_extra_length",
    "extra_length": "architrave_extra_length",
    "extra_w": "architrave_extra_width",
    "extra_width": "architrave_extra_width",
    "frame_h_thk": "frame_horizontal_thickness",
    "frame_v_thk": "frame_vertical_thickness",
}


DEFAULT_VALUES = {
    "opening_length": 0.0,
    "opening_width": 0.0,
    "vertical_clearance": 0.0,
    "horizontal_clearance": 0.0,
    "architrave_extra_length": 0.0,
    "architrave_extra_width": 0.0,
    "frame_horizontal_thickness": 0.0,
    "frame_vertical_thickness": 0.0,
    "lh_quantity": 0.0,
    "rh_quantity": 0.0,
    "shutter_thickness": 0.0,
    "allowance": 0.0,
    "groove": 0.0,
    "cut": 0.0,
    "offset": 0.0,
}


COMPONENT_INPUT_KEYS = {
    "vertical_clearance",
    "horizontal_clearance",
    "architrave_extra_length",
    "architrave_extra_width",
    "frame_horizontal_thickness",
    "frame_vertical_thickness",
    "shutter_thickness",
    "lh_quantity",
    "rh_quantity",
}


FIXED_COMPONENT_DIMENSIONS = {
    "architrave_vertical": {
        "width": Decimal("40"),
        "thickness": Decimal("12"),
    },
    "architrave_horizontal": {
        "width": Decimal("40"),
        "thickness": Decimal("12"),
    },
    "door_frame_vertical_beading": {
        "width": Decimal("27"),
        "thickness": Decimal("11"),
    },
    "door_frame_horizontal_beading": {
        "width": Decimal("27"),
        "thickness": Decimal("11"),
    },
    "door_frame_vertical_beading_1": {
        "width": Decimal("15"),
        "thickness": Decimal("7"),
    },
    "door_frame_horizontal_beading_1": {
        "width": Decimal("15"),
        "thickness": Decimal("7"),
    },
    "door_frame_horizontal_beading_2": {
        "width": Decimal("20"),
        "thickness": Decimal("8"),
    },
    "louver": {
        "width": Decimal("41.5"),
        "thickness": Decimal("7.5"),
    },
}


FORMULA_FUNCTION_NAMES = {
    "abs",
    "min",
    "max",
    "round",
    "float",
    "int",
    "Decimal",
}


def normalize_variable(var_name):
    var_name = str(var_name).strip()
    return VARIABLE_ALIASES.get(var_name, var_name)


def normalize_formula(formula):
    formula = str(formula or "").strip()

    if "=" in formula:
        left, right = formula.split("=", 1)

        if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*", left):
            formula = right.strip()

    for old_var, new_var in VARIABLE_ALIASES.items():
        formula = re.sub(rf"\b{old_var}\b", new_var, formula)

    return formula


def safe_execute(conn, cur, query, params=None):
    try:
        cur.execute(query, params or ())
    except Exception as e:
        conn.rollback()
        raise e


def get_distinct_values(conn, cur, table, column, where_sql="", params=None):
    query = f"""
        SELECT DISTINCT {column}
        FROM {table}
        {where_sql}
        ORDER BY {column}
    """
    safe_execute(conn, cur, query, params)
    return [r[0] for r in cur.fetchall() if r[0] is not None]


def extract_formula_variables(formula):
    formula = normalize_formula(formula)

    if not formula:
        return []

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        formula
    )

    return sorted({
        normalize_variable(v)
        for v in variables
        if v not in FORMULA_FUNCTION_NAMES
    })


def evaluate_formula(formula, variables):
    formula = normalize_formula(formula)

    if not formula:
        raise FormulaError("Formula empty")

    clean_vars = {}

    for key, value in variables.items():
        if value not in [None, ""]:
            clean_vars[normalize_variable(key)] = float(value)

    clean_vars.update({
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
    })

    try:
        result = eval(
            formula,
            {"__builtins__": {}},
            clean_vars
        )
        return Decimal(str(round(result, 2)))

    except NameError as e:
        raise FormulaError(f"Missing variable: {e}")

    except Exception as e:
        raise FormulaError(str(e))


def slug(value):
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def labelize_key(key):
    return str(key or "").replace("_", " ").title()


def clean_number(value):
    if value in [None, ""]:
        return None

    try:
        return float(value)
    except Exception:
        return None


def clean_int(value):
    number = clean_number(value)

    if number is None or pd.isna(number):
        return 0

    return int(float(number))


def fixed_value(formula, quantity):
    formula_num = clean_number(formula)

    if formula_num is not None:
        return Decimal(str(round(formula_num, 2)))

    quantity_num = clean_number(quantity)

    if quantity_num is not None:
        return Decimal(str(round(quantity_num, 2)))

    return None


def base_quantity(component, quantity, previous_qty):
    component_key = slug(component)

    if component_key == "flush_shutter":
        return 1

    if component_key == "architrave_vertical":
        return 4

    if quantity not in [None, ""]:
        return int(float(quantity))

    return int(previous_qty.get(component_key, 1))


def manual_dimension_key(component, attribute):
    return f"manual_{slug(component)}_{slug(attribute)}"


def fixed_dimension_value(component, attribute):
    component_key = slug(component)
    attribute_key = slug(attribute)

    return FIXED_COMPONENT_DIMENSIONS.get(
        component_key,
        {}
    ).get(attribute_key)


def has_fixed_dimension(component, attribute):
    return fixed_dimension_value(component, attribute) is not None


def existing_component_input_key(component, attribute):
    key = f"{slug(component)}_{slug(attribute)}"
    return key if key in COMPONENT_INPUT_KEYS else None


def apply_fixed_component_value(component, attribute, value):
    fixed_value_for_component = fixed_dimension_value(component, attribute)

    if fixed_value_for_component is not None:
        return fixed_value_for_component

    return value


def is_formula_type(rule_type):
    return str(rule_type or "").strip().lower() in ["formula", "fomula"]


def rule_output_keys(component, attribute):
    component_key = slug(component)
    attribute_key = slug(attribute)

    return {
        component_key,
        f"{component_key}_{attribute_key}",
    }


def product_calculated_keys(rules):
    keys = set()

    for component, attribute, *_ in rules:
        keys.update(rule_output_keys(component, attribute))

    return keys


def product_user_input_keys(rules):
    calculated_keys = product_calculated_keys(rules)
    required_inputs = set()

    for component, attribute, rule_type, formula, _ in rules:
        input_key = existing_component_input_key(component, attribute)

        if input_key:
            required_inputs.add(input_key)

        if is_formula_type(rule_type):
            for variable in extract_formula_variables(formula):
                variable = normalize_variable(variable)

                if variable in FORMULA_FUNCTION_NAMES:
                    continue

                if variable in calculated_keys:
                    continue

                if variable in ["lh_quantity", "rh_quantity"]:
                    continue

                required_inputs.add(variable)

    return sorted(required_inputs)


def needs_manual_dimension(rule):
    component, attribute, rule_type, formula, _ = rule
    attribute_key = slug(attribute)
    rule_type = str(rule_type or "").strip().lower()
    formula = normalize_formula(formula)

    if existing_component_input_key(component, attribute):
        return False

    return (
        attribute_key in ["width", "thickness"]
        and not has_fixed_dimension(component, attribute)
        and rule_type not in ["formula", "fomula"]
        and formula == ""
    )


def selected_component_manual_dimensions(rules):
    component_attributes = {}

    for component, attribute, rule_type, formula, _ in rules:
        component_key = slug(component)
        attribute_key = slug(attribute)

        if component_key not in component_attributes:
            component_attributes[component_key] = {
                "component": component,
                "attributes": set(),
            }

        component_attributes[component_key]["attributes"].add(attribute_key)

    manual_dimensions = []

    for component_data in component_attributes.values():
        component = component_data["component"]
        attributes = component_data["attributes"]

        for attribute in ["width", "thickness"]:
            if has_fixed_dimension(component, attribute):
                continue

            if existing_component_input_key(component, attribute):
                continue

            if attribute not in attributes:
                manual_dimensions.append((component, attribute))

    for rule in rules:
        if needs_manual_dimension(rule):
            component, attribute, _, _, _ = rule
            item = (component, attribute)

            if item not in manual_dimensions:
                manual_dimensions.append(item)

    return manual_dimensions


def store_calculated_value(variables, component, attribute, value):
    if value is None:
        return

    component_key = slug(component)
    attribute_key = slug(attribute)
    numeric_value = float(value)

    keys = {
        component_key,
        f"{component_key}_{attribute_key}",
    }

    if attribute_key in ["length", "width", "height", "thickness"]:
        keys.add(f"{component_key}_{attribute_key}")

    for key in keys:
        variables[key] = numeric_value


def get_dimension_value(component, attribute, variables):
    fixed_value_for_component = fixed_dimension_value(component, attribute)

    if fixed_value_for_component is not None:
        return fixed_value_for_component

    input_key = existing_component_input_key(component, attribute)

    if input_key:
        return Decimal(str(round(float(variables.get(input_key, 0.0)), 2)))

    return Decimal(str(round(
        float(variables.get(
            manual_dimension_key(component, attribute),
            0.0
        )),
        2
    )))


def calculate_cft(length, width, thickness, quantity, round_value=True):
    length_num = clean_number(length)
    width_num = clean_number(width)
    thickness_num = clean_number(thickness)
    quantity_num = clean_number(quantity)

    if None in [length_num, width_num, thickness_num, quantity_num]:
        return Decimal("0.00")

    cft = length_num * width_num * thickness_num / 1000000000 * 35.315 * quantity_num

    if round_value:
        return Decimal(str(round(cft, 2)))

    return Decimal(str(cft))


def ensure_generated_components_table(conn, cur):
    safe_execute(conn, cur, """
        CREATE TABLE IF NOT EXISTS generated_components (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_name TEXT NOT NULL,
            unit_type TEXT NOT NULL,
            house_number TEXT NOT NULL,
            product_cat TEXT NOT NULL,
            product_code TEXT NOT NULL,
            component TEXT NOT NULL,
            attribute TEXT NOT NULL,
            calculated_value TEXT,
            width NUMERIC,
            thickness NUMERIC,
            cft NUMERIC,
            orientation TEXT,
            qty INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    safe_execute(conn, cur, """
        ALTER TABLE generated_components
        ADD COLUMN IF NOT EXISTS cft NUMERIC
    """)

    safe_execute(conn, cur, """
        CREATE TABLE IF NOT EXISTS tracking (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_name TEXT NOT NULL,
            house_number TEXT NOT NULL,
            component TEXT NOT NULL,
            required_qty INTEGER,
            completed_qty INTEGER DEFAULT 0,
            pending_qty INTEGER,
            status TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()


def show_component_calculator(conn, cur):

    st.title("Component Calculator")

    ensure_generated_components_table(conn, cur)

    projects = get_distinct_values(conn, cur, "projects", "project_name")

    if not projects:
        st.warning("No projects found. Upload project master first.")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        project_name = st.selectbox("Project", projects)

    unit_types = get_distinct_values(
        conn,
        cur,
        "unit_types",
        "unit_type",
        "WHERE project_name = %s",
        (project_name,)
    )

    if not unit_types:
        st.warning("No unit types found for selected project.")
        return

    with col2:
        unit_type = st.selectbox("Unit Type", unit_types)

    houses = get_distinct_values(
        conn,
        cur,
        "houses",
        "house_number",
        "WHERE project_name = %s AND unit_type = %s",
        (project_name, unit_type)
    )

    with col3:
        selected_houses = st.multiselect(
            "House Number",
            houses,
            default=houses[:1]
        )

    safe_execute(conn, cur, """
        SELECT DISTINCT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
    """)

    products = cur.fetchall()

    if not products:
        st.warning("No products found. Upload component architecture first.")
        return

    product_options = [f"{p[0]} | {p[1]}" for p in products]

    with col4:
        selected_product = st.selectbox("Product", product_options)

    product_cat, product_code = selected_product.split(" | ", 1)

    safe_execute(conn, cur, """
        SELECT
            component,
            attribute,
            type,
            formula_used,
            quantity
        FROM product_component_rules
        WHERE product_cat = %s
        AND product_code = %s
    """, (product_cat, product_code))

    rules = cur.fetchall()

    if not rules:
        st.warning("No component rules found for selected product.")
        return

    required_input_keys_all = product_user_input_keys(rules)

    st.markdown("---")
    st.subheader("House Wise LH / RH Quantity")

    house_qty_df = pd.DataFrame({
        "House Number": selected_houses,
        "LH Quantity": [0 for _ in selected_houses],
        "RH Quantity": [0 for _ in selected_houses],
    })

    edited_house_qty_df = st.data_editor(
        house_qty_df,
        use_container_width=True,
        hide_index=True,
        key=f"house_wise_lh_rh_qty_{product_cat}_{product_code}",
        disabled=["House Number"]
    )

    house_qty_map = {
        str(row["House Number"]): {
            "lh_quantity": clean_int(row["LH Quantity"]),
            "rh_quantity": clean_int(row["RH Quantity"]),
        }
        for _, row in edited_house_qty_df.iterrows()
    }

    total_lh_quantity = sum(
        item["lh_quantity"]
        for item in house_qty_map.values()
    )

    total_rh_quantity = sum(
        item["rh_quantity"]
        for item in house_qty_map.values()
    )

    st.info(
        f"Total LH Quantity: {total_lh_quantity} | Total RH Quantity: {total_rh_quantity} | Total Quantity: {total_lh_quantity + total_rh_quantity}"
    )

    st.markdown("---")
    st.subheader("User Based Data")

    variables = {}

    opening_keys = [
        key for key in ["opening_length", "opening_width"]
        if key in required_input_keys_all
    ]

    if opening_keys:
        st.markdown("#### Opening Size")
        open_col1, open_col2 = st.columns(2)

        if "opening_length" in opening_keys:
            with open_col1:
                variables["opening_length"] = st.number_input(
                    "Opening Length",
                    value=float(DEFAULT_VALUES["opening_length"]),
                    step=1.0,
                    format="%.2f",
                    key=f"input_{product_cat}_{product_code}_opening_length"
                )

        if "opening_width" in opening_keys:
            with open_col2:
                variables["opening_width"] = st.number_input(
                    "Opening Width",
                    value=float(DEFAULT_VALUES["opening_width"]),
                    step=1.0,
                    format="%.2f",
                    key=f"input_{product_cat}_{product_code}_opening_width"
                )

    component_input_keys = [
        key for key in required_input_keys_all
        if key not in ["opening_length", "opening_width"]
    ]

    if component_input_keys:
        st.markdown("#### Component Inputs")
        input_cols = st.columns(4)

        for idx, key in enumerate(component_input_keys):
            with input_cols[idx % 4]:
                variables[key] = st.number_input(
                    labelize_key(key),
                    value=float(DEFAULT_VALUES.get(key, 0.0)),
                    step=1.0,
                    format="%.2f",
                    key=f"input_{product_cat}_{product_code}_{key}"
                )

    manual_dimensions = selected_component_manual_dimensions(rules)

    if manual_dimensions:
        st.markdown("#### Manual Component Dimensions")
        manual_cols = st.columns(4)

        for idx, (component, attribute) in enumerate(manual_dimensions):
            key = manual_dimension_key(component, attribute)

            with manual_cols[idx % 4]:
                variables[key] = st.number_input(
                    f"{component} {attribute}".title(),
                    value=0.0,
                    step=1.0,
                    format="%.2f",
                    key=f"manual_input_{product_cat}_{product_code}_{slug(component)}_{slug(attribute)}_{idx}"
                )

    if not required_input_keys_all and not manual_dimensions:
        st.info("No user based inputs required for this product.")

    st.markdown("---")

    if st.button("Generate Components"):

        if not selected_houses:
            st.warning("Please select at least one house number.")
            return

        if not house_qty_map:
            st.warning("Please enter house-wise LH/RH Quantity.")
            return

        preview_rows = []
        tracking_rows = []
        errors_found = False

        for house_number in selected_houses:

            house_qty = house_qty_map.get(str(house_number), {})
            lh_quantity = int(float(house_qty.get("lh_quantity", 0)))
            rh_quantity = int(float(house_qty.get("rh_quantity", 0)))
            product_qty_multiplier = lh_quantity + rh_quantity

            if product_qty_multiplier <= 0:
                st.warning(f"Please enter LH Quantity or RH Quantity for house {house_number}.")
                errors_found = True
                continue

            house_variables = variables.copy()
            house_variables["lh_quantity"] = lh_quantity
            house_variables["rh_quantity"] = rh_quantity

            pending_rules = list(rules)
            calculated_rules = []
            previous_qty = {}
            component_tracking_map = {}

            while pending_rules:
                progressed = False
                next_pending = []

                for rule in pending_rules:
                    component = str(rule[0]).strip()
                    attribute = str(rule[1]).strip()
                    rule_type = str(rule[2] or "").strip().lower()
                    formula = rule[3]
                    quantity = rule[4]

                    component_qty = base_quantity(
                        component,
                        quantity,
                        previous_qty
                    )

                    total_quantity = int(
                        component_qty * product_qty_multiplier
                    )

                    try:
                        if rule_type in ["formula", "fomula"]:
                            value = evaluate_formula(formula, house_variables)

                        elif needs_manual_dimension(rule):
                            value = get_dimension_value(
                                component,
                                attribute,
                                variables
                            )

                        else:
                            value = fixed_value(formula, quantity)

                        if value is None:
                            value = Decimal("0")

                        value = apply_fixed_component_value(
                            component,
                            attribute,
                            value
                        )

                        store_calculated_value(
                            house_variables,
                            component,
                            attribute,
                            value
                        )

                        previous_qty[slug(component)] = component_qty

                        calculated_rules.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalize_formula(formula),
                            "Value": value,
                            "Base Quantity": component_qty,
                            "Total Quantity": total_quantity,
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
                        })

                        tracking_key = (
                            house_number,
                            product_cat,
                            product_code,
                            component
                        )

                        if tracking_key not in component_tracking_map:
                            component_tracking_map[tracking_key] = {
                                "project_name": project_name,
                                "unit_type": unit_type,
                                "house_number": house_number,
                                "product_cat": product_cat,
                                "product_code": product_code,
                                "orientation": "",
                                "component": component,
                                "quantity": total_quantity,
                                "attributes": {}
                            }

                        component_tracking_map[tracking_key]["attributes"][attribute] = {
                            "type": "formula" if rule_type == "fomula" else rule_type,
                            "formula": normalize_formula(formula),
                            "value": float(value),
                            "base_quantity": component_qty,
                        }

                        progressed = True

                    except FormulaError as e:
                        if "Missing variable" in str(e):
                            next_pending.append(rule)
                        else:
                            errors_found = True
                            st.error(f"{house_number} - {component} / {attribute}: {e}")

                    except Exception as e:
                        errors_found = True
                        st.error(f"{house_number} - {component} / {attribute}: {e}")

                if not progressed:
                    for rule in next_pending:
                        component = str(rule[0]).strip()
                        attribute = str(rule[1]).strip()
                        formula = rule[3]
                        quantity = rule[4]
                        rule_type = str(rule[2] or "").strip().lower()

                        component_qty = base_quantity(
                            component,
                            quantity,
                            previous_qty
                        )

                        preview_rows.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalize_formula(formula),
                            "Value": None,
                            "Base Quantity": component_qty,
                            "Total Quantity": int(component_qty * product_qty_multiplier),
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
                        })

                        missing = ", ".join(extract_formula_variables(formula))

                        st.error(
                            f"{house_number} - {component} / {attribute}: Missing dependency. Required: {missing}"
                        )

                    errors_found = True
                    break

                pending_rules = next_pending

            for row in component_tracking_map.values():
                for attribute in ["width", "thickness"]:
                    if attribute in row["attributes"]:
                        continue

                    value = get_dimension_value(
                        row["component"],
                        attribute,
                        variables
                    )

                    row["attributes"][attribute] = {
                        "type": "manual",
                        "formula": "",
                        "value": float(value),
                        "base_quantity": base_quantity(row["component"], None, previous_qty),
                    }

                    calculated_rules.append({
                        "House Number": house_number,
                        "Product": product_code,
                        "Component": row["component"],
                        "Attribute": attribute,
                        "Type": "manual",
                        "Formula": "",
                        "Value": value,
                        "Base Quantity": base_quantity(row["component"], None, previous_qty),
                        "Total Quantity": row["quantity"],
                        "LH Quantity": lh_quantity,
                        "RH Quantity": rh_quantity,
                    })

            preview_rows.extend(calculated_rules)
            tracking_rows.extend(component_tracking_map.values())

        st.session_state["generated_component_preview"] = preview_rows
        st.session_state["generated_component_tracking_rows"] = tracking_rows
        st.session_state["generated_component_errors"] = errors_found
        st.session_state["generated_lh_quantity"] = total_lh_quantity
        st.session_state["generated_rh_quantity"] = total_rh_quantity
        st.session_state["generated_shutter_thickness"] = variables.get(
            "shutter_thickness",
            ""
        )

    if "generated_component_preview" in st.session_state:

        st.subheader("Generated Components")

        generated_lh = st.session_state.get("generated_lh_quantity", 0)
        generated_rh = st.session_state.get("generated_rh_quantity", 0)

        st.info(
            f"Total LH Quantity: {generated_lh} | Total RH Quantity: {generated_rh} | Total Quantity: {generated_lh + generated_rh}"
        )

        df_preview_raw = pd.DataFrame(
            st.session_state["generated_component_preview"]
        )

        if df_preview_raw.empty:
            st.warning("No components generated.")
            return

        house_rows = []

        group_cols = [
            "House Number",
            "Product",
            "Component",
            "Total Quantity",
            "LH Quantity",
            "RH Quantity",
        ]

        for _, group_df in df_preview_raw.groupby(
            group_cols,
            dropna=False,
            sort=False
        ):
            first_row = group_df.iloc[0].to_dict()
            values = {}

            for _, row in group_df.iterrows():
                attr = str(row["Attribute"]).strip().lower()
                values[attr] = row["Value"]

            component_name = str(
                first_row["Component"]
            ).strip().lower()

            length_value = values.get("length", "")
            thickness_value = values.get(
                "thickness",
                values.get("height", "")
            )

            width_value = values.get("width", "")

            fixed_width = fixed_dimension_value(component_name, "width")
            fixed_thickness = fixed_dimension_value(component_name, "thickness")

            if fixed_width is not None:
                width_value = fixed_width

            if fixed_thickness is not None:
                thickness_value = fixed_thickness

            if component_name == "flush shutter":
                thickness_value = st.session_state.get(
                    "generated_shutter_thickness",
                    ""
                )

            cft_value = calculate_cft(
                length_value,
                width_value,
                thickness_value,
                first_row["Total Quantity"],
                round_value=True
            )

            cft_total_value = calculate_cft(
                length_value,
                width_value,
                thickness_value,
                first_row["Total Quantity"],
                round_value=False
            )

            house_rows.append({
                "House Number": first_row["House Number"],
                "Product": first_row["Product"],
                "Component": first_row["Component"],
                "Length": length_value,
                "Width": width_value,
                "Thickness": thickness_value,
                "Total Quantity": first_row["Total Quantity"],
                "LH Quantity": first_row["LH Quantity"],
                "RH Quantity": first_row["RH Quantity"],
                "CFT": cft_value,
                "CFT Raw": cft_total_value,
            })

        display_rows = []

        df_house_rows = pd.DataFrame(house_rows)

        if not df_house_rows.empty:
            aggregate_cols = [
                "Product",
                "Component",
                "Length",
                "Width",
                "Thickness",
            ]

            for _, group_df in df_house_rows.groupby(
                aggregate_cols,
                dropna=False,
                sort=False
            ):
                first_row = group_df.iloc[0].to_dict()

                house_numbers = [
                    str(value)
                    for value in group_df["House Number"].tolist()
                ]

                lh_values = [
                    f'{row["House Number"]}: {int(row["LH Quantity"])}'
                    for _, row in group_df.iterrows()
                ]

                rh_values = [
                    f'{row["House Number"]}: {int(row["RH Quantity"])}'
                    for _, row in group_df.iterrows()
                ]

                total_quantity = sum(
                    clean_int(value)
                    for value in group_df["Total Quantity"].tolist()
                )

                total_cft_raw = sum(
                    clean_number(value) or 0
                    for value in group_df["CFT Raw"].tolist()
                )

                display_rows.append({
                    "House Number": "\n".join(house_numbers),
                    "Product": first_row["Product"],
                    "Component": first_row["Component"],
                    "Length": first_row["Length"],
                    "Width": first_row["Width"],
                    "Thickness": first_row["Thickness"],
                    "LH Quantity": "\n".join(lh_values),
                    "RH Quantity": "\n".join(rh_values),
                    "Total Quantity": total_quantity,
                    "CFT": Decimal(str(round(total_cft_raw, 2))),
                    "CFT Raw": total_cft_raw,
                })

        total_cft = sum(
            clean_number(row.get("CFT Raw")) or 0
            for row in display_rows
        )

        display_rows.append({
            "House Number": "",
            "Product": "",
            "Component": "CFT Total",
            "Length": "",
            "Width": "",
            "Thickness": "",
            "LH Quantity": "",
            "RH Quantity": "",
            "Total Quantity": "",
            "CFT": Decimal(str(round(total_cft, 2))),
            "CFT Raw": total_cft,
        })

        df_preview = pd.DataFrame(display_rows)

        if "CFT Raw" in df_preview.columns:
            df_preview = df_preview.drop(columns=["CFT Raw"])

        st.dataframe(
            df_preview,
            use_container_width=True,
            hide_index=True
        )

        errors_found = st.session_state.get(
            "generated_component_errors",
            False
        )

        if errors_found or df_preview_raw["Value"].isna().any():
            st.warning("Some components did not calculate. Fix formulas before confirming.")
        else:
            st.success("All component formulas calculated successfully")

        st.markdown("---")

        if st.button("Confirm Components and Send to Tracking", type="primary"):

            if errors_found or df_preview_raw["Value"].isna().any():
                st.warning("Please fix formula errors before sending to tracking.")
                return

            tracking_rows = st.session_state.get(
                "generated_component_tracking_rows",
                []
            )

            if not tracking_rows:
                st.warning("No generated components to save.")
                return

            try:
                generated_insert_rows = []
                tracking_insert_rows = []

                for row in tracking_rows:
                    attrs = row["attributes"]

                    length_value = ""
                    width_value = None
                    thickness_value = None

                    if "length" in attrs:
                        length_value = str(attrs["length"]["value"])

                    if "width" in attrs:
                        width_value = attrs["width"]["value"]

                    if "thickness" in attrs:
                        thickness_value = attrs["thickness"]["value"]

                    fixed_width = fixed_dimension_value(row["component"], "width")
                    fixed_thickness = fixed_dimension_value(row["component"], "thickness")

                    if fixed_width is not None:
                        width_value = fixed_width

                    if fixed_thickness is not None:
                        thickness_value = fixed_thickness

                    if str(row["component"]).strip().lower() == "flush shutter":
                        thickness_value = st.session_state.get(
                            "generated_shutter_thickness",
                            None
                        )

                    cft_value = calculate_cft(
                        length_value,
                        width_value,
                        thickness_value,
                        row["quantity"],
                        round_value=True
                    )

                    generated_insert_rows.append((
                        row["project_name"],
                        row["unit_type"],
                        row["house_number"],
                        row["product_cat"],
                        row["product_code"],
                        row["component"],
                        "combined",
                        length_value,
                        width_value,
                        thickness_value,
                        cft_value,
                        row["orientation"],
                        row["quantity"],
                    ))

                    tracking_insert_rows.append((
                        row["project_name"],
                        row["house_number"],
                        row["component"],
                        row["quantity"],
                        0,
                        row["quantity"],
                        "Pending",
                    ))

                execute_values(
                    cur,
                    """
                    INSERT INTO generated_components
                    (
                        project_name,
                        unit_type,
                        house_number,
                        product_cat,
                        product_code,
                        component,
                        attribute,
                        calculated_value,
                        width,
                        thickness,
                        cft,
                        orientation,
                        qty
                    )
                    VALUES %s
                    """,
                    generated_insert_rows
                )

                execute_values(
                    cur,
                    """
                    INSERT INTO tracking
                    (
                        project_name,
                        house_number,
                        component,
                        required_qty,
                        completed_qty,
                        pending_qty,
                        status
                    )
                    VALUES %s
                    """,
                    tracking_insert_rows
                )

                conn.commit()

                st.success(
                    f"{len(generated_insert_rows)} component(s) sent to tracking successfully"
                )

            except Exception as e:
                conn.rollback()
                st.error(f"Failed to send components to tracking: {e}")
