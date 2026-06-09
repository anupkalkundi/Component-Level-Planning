import re
from decimal import Decimal
from io import BytesIO

import pandas as pd
import streamlit as st
from psycopg2.extras import execute_values


class FormulaError(Exception):
    pass


def fetch_df(cur, query, params=None):
    cur.execute(query, params or ())
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    return pd.DataFrame(rows, columns=cols)


def slug(value):
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def label_from_key(key):
    return str(key).replace("_", " ").title()


def clean_number(value):
    if value in [None, ""]:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        return float(value)
    except Exception:
        return None


def clean_int(value):
    number = clean_number(value)

    if number is None:
        return 0

    return int(float(number))


def decimal_value(value):
    number = clean_number(value)

    if number is None:
        return Decimal("0")

    return Decimal(str(round(number, 2)))


def clean_display_number(value):
    number = clean_number(value)

    if number is None:
        return ""

    if float(number).is_integer():
        return int(number)

    return round(number, 2)


def is_flush_component(component):
    component_key = slug(component)
    return component_key in {
        "flush_door",
        "flush_shutter",
        "flush_door_shutter",
    } or "flush_door" in component_key or "flush_shutter" in component_key


def product_uses_lh_rh(product_cat, product_code, rules):
    text = slug(f"{product_cat} {product_code}")

    if "door" in text or "shutter" in text:
        return True

    formula_vars = set()

    for rule in rules:
        if str(rule.get("rule_type") or "").lower() == "formula":
            formula_vars.update(extract_formula_variables(rule.get("formula_used")))

    return "lh_quantity" in formula_vars or "rh_quantity" in formula_vars


def get_table_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (table_name,)
    )
    return {row[0] for row in cur.fetchall()}


def get_distinct_values(cur, table_name, column_name, where_sql="", params=None):
    cur.execute(
        f"""
        SELECT DISTINCT {column_name}
        FROM {table_name}
        {where_sql}
        ORDER BY {column_name}
        """,
        params or ()
    )
    return [row[0] for row in cur.fetchall() if row[0] is not None]


def load_product_rules(cur, product_cat, product_code):
    cur.execute(
        """
        SELECT
            product_cat,
            product_code,
            component,
            attribute,
            "type" AS rule_type,
            formula_used,
            fixed_value,
            quantity,
            display_order
        FROM product_component_rules
        WHERE product_cat = %s
          AND product_code = %s
        ORDER BY component, display_order
        """,
        (product_cat, product_code)
    )

    col_names = [desc[0] for desc in cur.description]
    return [dict(zip(col_names, row)) for row in cur.fetchall()]


def calculated_variable_keys(rules):
    keys = set()

    for rule in rules:
        component = slug(rule["component"])
        attribute = slug(rule["attribute"])

        keys.add(component)
        keys.add(f"{component}_{attribute}")

    return keys


def extract_formula_variables(formula):
    formula = str(formula or "")

    if not formula.strip():
        return set()

    names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", formula)

    ignored = {
        "abs",
        "min",
        "max",
        "round",
        "int",
        "float",
    }

    return {
        slug(name)
        for name in names
        if slug(name) not in ignored
    }


def required_formula_inputs(rules):
    inputs = set()

    for rule in rules:
        rule_type = str(rule["rule_type"] or "").lower()

        if rule_type == "formula":
            inputs.update(extract_formula_variables(rule["formula_used"]))

    inputs -= calculated_variable_keys(rules)
    inputs.discard("lh_quantity")
    inputs.discard("rh_quantity")
    inputs.discard("quantity")

    return sorted(inputs)


def required_manual_inputs(rules):
    inputs = []

    for rule in rules:
        rule_type = str(rule["rule_type"] or "").lower()
        attribute = slug(rule["attribute"])

        if rule_type != "manual":
            continue

        if attribute == "quantity":
            continue

        key = f"manual_{slug(rule['component'])}_{attribute}"
        label = f"{rule['component']} {rule['attribute']}"

        inputs.append({
            "key": key,
            "label": label,
            "component": rule["component"],
            "attribute": rule["attribute"],
        })

    return inputs


def safe_eval_formula(formula, variables):
    formula = str(formula or "").strip()

    if not formula:
        raise FormulaError("Formula is empty.")

    allowed_names = {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
    }

    clean_variables = {}

    for key, value in variables.items():
        clean_variables[slug(key)] = float(value)

    eval_scope = {}
    eval_scope.update(allowed_names)
    eval_scope.update(clean_variables)

    try:
        result = eval(formula, {"__builtins__": {}}, eval_scope)
        return Decimal(str(round(float(result), 2)))

    except NameError as e:
        missing = str(e)
        raise FormulaError(f"Missing input in formula: {missing}")

    except Exception as e:
        raise FormulaError(str(e))


def get_component_quantity(component_rules):
    for rule in component_rules:
        if slug(rule["attribute"]) != "quantity":
            continue

        qty = clean_number(rule.get("quantity"))

        if qty is not None:
            return int(qty)

        fixed_qty = clean_number(rule.get("fixed_value"))

        if fixed_qty is not None:
            return int(fixed_qty)

    return 1


def calculate_cft(length, width, thickness, qty, component=None):
    if is_flush_component(component):
        return Decimal("0.00")

    length_num = clean_number(length) or 0
    width_num = clean_number(width) or 0
    thickness_num = clean_number(thickness) or 0
    quantity_num = clean_number(qty) or 0

    if length_num <= 0 or width_num <= 0 or thickness_num <= 0 or quantity_num <= 0:
        return Decimal("0.00")

    cft = length_num * width_num * thickness_num / 1000000000 * 35.315 * quantity_num
    return Decimal(str(round(cft, 2)))


def store_calculated_variable(variables, component, attribute, value):
    component_key = slug(component)
    attribute_key = slug(attribute)

    variables[f"{component_key}_{attribute_key}"] = float(value)

    if attribute_key == "length":
        variables[component_key] = float(value)


def calculate_rules(rules, user_inputs):
    variables = dict(user_inputs)
    pending_rules = [
        rule for rule in rules
        if slug(rule["attribute"]) != "quantity"
    ]

    calculated = []
    loop_count = 0

    while pending_rules:
        loop_count += 1

        if loop_count > 50:
            raise FormulaError("Formula dependency loop found.")

        progressed = False
        next_pending = []

        for rule in pending_rules:
            component = rule["component"]
            attribute = rule["attribute"]
            rule_type = str(rule["rule_type"] or "").lower()

            try:
                if rule_type == "fixed":
                    value = decimal_value(rule["fixed_value"])

                elif rule_type == "manual":
                    manual_key = f"manual_{slug(component)}_{slug(attribute)}"
                    value = decimal_value(variables.get(manual_key))

                elif rule_type == "formula":
                    value = safe_eval_formula(rule["formula_used"], variables)

                else:
                    value = Decimal("0")

                store_calculated_variable(variables, component, attribute, value)

                calculated.append({
                    "component": component,
                    "attribute": attribute,
                    "type": rule_type,
                    "formula": rule["formula_used"],
                    "value": value,
                })

                progressed = True

            except FormulaError as e:
                if "Missing input" in str(e) or "name" in str(e).lower():
                    next_pending.append(rule)
                else:
                    raise

        if not progressed:
            missing_items = [
                f"{rule['component']} {rule['attribute']}"
                for rule in next_pending
            ]
            raise FormulaError(
                "Cannot calculate: " + ", ".join(missing_items)
            )

        pending_rules = next_pending

    return calculated, variables


def build_component_summary(rules, calculated_rows, product_qty):
    rules_by_component = {}

    for rule in rules:
        component = rule["component"]

        if component not in rules_by_component:
            rules_by_component[component] = []

        rules_by_component[component].append(rule)

    calculated_by_component = {}

    for row in calculated_rows:
        component = row["component"]
        attribute = slug(row["attribute"])

        if component not in calculated_by_component:
            calculated_by_component[component] = {}

        calculated_by_component[component][attribute] = row["value"]

    summary_rows = []

    for component, component_rules in rules_by_component.items():
        base_qty = get_component_quantity(component_rules)
        total_qty = int(base_qty * product_qty)

        values = calculated_by_component.get(component, {})

        length = values.get("length", Decimal("0"))
        width = values.get("width", Decimal("0"))
        thickness = values.get("thickness", Decimal("0"))

        cft = calculate_cft(length, width, thickness, total_qty, component)

        summary_rows.append({
            "Component": component,
            "Length": clean_display_number(length),
            "Width": clean_display_number(width),
            "Thickness": clean_display_number(thickness),
            "Qty": total_qty,
            "CFT": cft,
        })

    return summary_rows


def build_components_excel(
    project_name,
    unit_type,
    product_code,
    total_lh_quantity,
    total_rh_quantity,
    total_quantity,
    prepared_by,
    preview_df,
):
    output = BytesIO()

    header_df = pd.DataFrame([
        ["Project", project_name],
        ["Unit Type", unit_type],
        ["Product", product_code],
        ["Total LH Quantity", total_lh_quantity],
        ["Total RH Quantity", total_rh_quantity],
        ["Total Quantity", total_quantity],
        ["Prepared By", prepared_by],
    ])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        header_df.to_excel(
            writer,
            sheet_name="Generated Components",
            index=False,
            header=False,
            startrow=0,
        )

        preview_df.to_excel(
            writer,
            sheet_name="Generated Components",
            index=False,
            startrow=9,
        )

        ws = writer.book["Generated Components"]

        for col in ws.columns:
            max_length = 0
            column_letter = col[0].column_letter

            for cell in col:
                value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(value))

            ws.column_dimensions[column_letter].width = min(max_length + 3, 45)

    output.seek(0)
    return output


def show_component_calculator(conn, cur):
    st.title("Component Calculator")

    projects = get_distinct_values(cur, "projects", "project_name")

    if not projects:
        st.info("No projects found.")
        return

    col1, col2 = st.columns(2)

    with col1:
        project_name = st.selectbox("Project", projects)

    unit_types = get_distinct_values(
        cur,
        "unit_types",
        "unit_type",
        "WHERE project_name = %s",
        (project_name,)
    )

    if not unit_types:
        st.info("No unit types found for this project.")
        return

    with col2:
        unit_type = st.selectbox("Unit Type", unit_types)

    houses = get_distinct_values(
        cur,
        "houses",
        "house_number",
        "WHERE project_name = %s AND unit_type = %s",
        (project_name, unit_type)
    )

    products_df = fetch_df(
        cur,
        """
        SELECT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
        """
    )

    if products_df.empty:
        st.info("No products found.")
        return

    product_options = {
        f"{row['product_cat']} - {row['product_code']}": {
            "product_cat": row["product_cat"],
            "product_code": row["product_code"],
        }
        for _, row in products_df.iterrows()
    }

    col1, col2 = st.columns(2)

    with col1:
        selected_product = st.selectbox(
            "Product",
            list(product_options.keys())
        )

    with col2:
        selected_houses = st.multiselect(
            "House Number",
            houses
        )

    product_cat = product_options[selected_product]["product_cat"]
    product_code = product_options[selected_product]["product_code"]

    state_key = f"{project_name}_{unit_type}_{product_cat}_{product_code}"

    rules = load_product_rules(cur, product_cat, product_code)

    if not rules:
        st.warning("No product definition found for this product.")
        return

    uses_lh_rh = product_uses_lh_rh(product_cat, product_code, rules)

    st.markdown("---")
    st.subheader("Required Inputs")

    formula_inputs = required_formula_inputs(rules)
    manual_inputs = required_manual_inputs(rules)

    user_inputs = {}

    if formula_inputs:
        st.markdown("#### Formula Inputs")
        formula_cols = st.columns(4)

        for idx, key in enumerate(formula_inputs):
            with formula_cols[idx % 4]:
                user_inputs[key] = st.number_input(
                    label_from_key(key),
                    value=0.0,
                    step=1.0,
                    format="%.2f",
                    key=f"formula_input_{state_key}_{key}"
                )

    if manual_inputs:
        st.markdown("#### Manual Inputs")
        manual_cols = st.columns(4)

        for idx, item in enumerate(manual_inputs):
            with manual_cols[idx % 4]:
                user_inputs[item["key"]] = st.number_input(
                    item["label"],
                    value=0.0,
                    step=1.0,
                    format="%.2f",
                    key=f"manual_input_{state_key}_{item['key']}"
                )

    if not formula_inputs and not manual_inputs:
        st.info("No user input required. Product uses only fixed values.")

    st.markdown("---")

    house_quantities = {}
    total_lh_quantity = 0
    total_rh_quantity = 0
    total_quantity = 0

    if selected_houses:
        st.subheader("Product Quantity")

        if uses_lh_rh:
            quantity_df = pd.DataFrame({
                "House Number": selected_houses,
                "LH Quantity": [0 for _ in selected_houses],
                "RH Quantity": [0 for _ in selected_houses],
            })

            edited_quantity_df = st.data_editor(
                quantity_df,
                use_container_width=True,
                hide_index=True,
                disabled=["House Number"],
                key=f"lh_rh_quantity_{state_key}",
            )

            for _, row in edited_quantity_df.iterrows():
                house_number = row["House Number"]
                lh_qty = clean_int(row["LH Quantity"])
                rh_qty = clean_int(row["RH Quantity"])
                qty = lh_qty + rh_qty

                house_quantities[house_number] = {
                    "lh_quantity": lh_qty,
                    "rh_quantity": rh_qty,
                    "quantity": qty,
                }

            total_lh_quantity = sum(item["lh_quantity"] for item in house_quantities.values())
            total_rh_quantity = sum(item["rh_quantity"] for item in house_quantities.values())
            total_quantity = total_lh_quantity + total_rh_quantity

            st.info(
                f"Total LH Quantity: {total_lh_quantity} | "
                f"Total RH Quantity: {total_rh_quantity} | "
                f"Total Quantity: {total_quantity}"
            )

        else:
            quantity_df = pd.DataFrame({
                "House Number": selected_houses,
                "Quantity": [1 for _ in selected_houses],
            })

            edited_quantity_df = st.data_editor(
                quantity_df,
                use_container_width=True,
                hide_index=True,
                disabled=["House Number"],
                key=f"product_quantity_{state_key}",
            )

            for _, row in edited_quantity_df.iterrows():
                house_number = row["House Number"]
                qty = clean_int(row["Quantity"])

                house_quantities[house_number] = {
                    "lh_quantity": 0,
                    "rh_quantity": 0,
                    "quantity": qty,
                }

            total_quantity = sum(item["quantity"] for item in house_quantities.values())

            st.info(f"Total Quantity: {total_quantity}")

    if st.button("Generate Components", type="primary"):
        if not selected_houses:
            st.warning("Select at least one house.")
            return

        preview_rows = []
        tracking_rows = []
        generated_insert_rows = []

        try:
            for house_number in selected_houses:
                house_qty = house_quantities.get(
                    house_number,
                    {"lh_quantity": 0, "rh_quantity": 0, "quantity": 1}
                )

                product_qty = int(house_qty["quantity"])

                if product_qty <= 0:
                    st.warning(f"Enter quantity for house {house_number}.")
                    continue

                house_inputs = dict(user_inputs)
                house_inputs["lh_quantity"] = house_qty["lh_quantity"]
                house_inputs["rh_quantity"] = house_qty["rh_quantity"]
                house_inputs["quantity"] = product_qty

                calculated_rows, variables = calculate_rules(rules, house_inputs)

                summary_rows = build_component_summary(
                    rules,
                    calculated_rows,
                    product_qty
                )

                for row in summary_rows:
                    preview_rows.append({
                        "House Number": house_number,
                        "Product": product_code,
                        "Component": row["Component"],
                        "Length": row["Length"],
                        "Width": row["Width"],
                        "Thickness": row["Thickness"],
                        "Qty": row["Qty"],
                        "CFT": row["CFT"],
                        "LH Quantity": house_qty["lh_quantity"],
                        "RH Quantity": house_qty["rh_quantity"],
                        "LH & RH Details": (
                            f"{house_qty['lh_quantity']}L, {house_qty['rh_quantity']}R"
                            if uses_lh_rh else ""
                        ),
                    })

                    generated_insert_rows.append((
                        project_name,
                        unit_type,
                        house_number,
                        product_cat,
                        product_code,
                        row["Component"],
                        "combined",
                        str(row["Length"]),
                        row["Width"],
                        row["Thickness"],
                        "",
                        row["Qty"],
                    ))

                    tracking_rows.append((
                        project_name,
                        house_number,
                        row["Component"],
                        row["Qty"],
                        0,
                        row["Qty"],
                        "Pending",
                    ))

            st.session_state["component_preview_rows"] = preview_rows
            st.session_state["component_generated_rows"] = generated_insert_rows
            st.session_state["component_tracking_rows"] = tracking_rows
            st.session_state["component_total_lh_quantity"] = total_lh_quantity
            st.session_state["component_total_rh_quantity"] = total_rh_quantity
            st.session_state["component_total_quantity"] = total_quantity
            st.session_state["component_uses_lh_rh"] = uses_lh_rh

        except FormulaError as e:
            st.error(f"Calculation error: {e}")
            return

        except Exception as e:
            st.error(f"Error: {e}")
            return

    if "component_preview_rows" in st.session_state:
        st.subheader("Generated Components")

        preview_df = pd.DataFrame(st.session_state["component_preview_rows"])

        total_lh_quantity = st.session_state.get("component_total_lh_quantity", 0)
        total_rh_quantity = st.session_state.get("component_total_rh_quantity", 0)
        total_quantity = st.session_state.get("component_total_quantity", 0)
        uses_lh_rh = st.session_state.get("component_uses_lh_rh", False)

        total_cft = sum(
            clean_number(value) or 0
            for value in preview_df["CFT"].tolist()
        )

        if uses_lh_rh:
            st.info(
                f"Total LH Quantity: {total_lh_quantity} | "
                f"Total RH Quantity: {total_rh_quantity} | "
                f"Total Quantity: {total_quantity}"
            )
        else:
            st.info(f"Total Quantity: {total_quantity}")

        total_row = {
            "House Number": "",
            "Product": "",
            "Component": "CFT Total",
            "Length": "",
            "Width": "",
            "Thickness": "",
            "Qty": "",
            "CFT": Decimal(str(round(total_cft, 2))),
            "LH Quantity": "",
            "RH Quantity": "",
            "LH & RH Details": "",
        }

        display_df = pd.concat(
            [preview_df, pd.DataFrame([total_row])],
            ignore_index=True
        )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        prepared_by = st.selectbox(
            "Prepared by",
            ["Anup", "Mani"],
            key=f"prepared_by_{state_key}"
        )

        excel_file = build_components_excel(
            project_name,
            unit_type,
            product_code,
            total_lh_quantity,
            total_rh_quantity,
            total_quantity,
            prepared_by,
            display_df,
        )

        st.download_button(
            "Download Excel",
            data=excel_file,
            file_name=f"{project_name}_{unit_type}_{product_code}_components.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_excel_{state_key}"
        )

        st.success("All component formulas calculated successfully")

        if st.button("Confirm Components and Send to Tracking", type="primary"):
            generated_rows = st.session_state.get("component_generated_rows", [])
            tracking_rows = st.session_state.get("component_tracking_rows", [])

            if not generated_rows:
                st.warning("No generated components to save.")
                return

            try:
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
                        orientation,
                        qty
                    )
                    VALUES %s
                    """,
                    generated_rows
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
                    tracking_rows
                )

                conn.commit()
                st.success("Components sent to tracking successfully.")

            except Exception as e:
                conn.rollback()
                st.error(f"Failed to save generated components: {e}")
