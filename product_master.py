import streamlit as st
import pandas as pd


def fetch_df(cur, query, params=None):
    cur.execute(query, params or ())
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return pd.DataFrame(rows, columns=columns)


def product_label(row):
    return f"{row['product_cat']} - {row['product_code']}"


def get_products(cur):
    return fetch_df(
        cur,
        """
        SELECT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
        """
    )


def normalize_rule_type(value):
    if not value:
        return "Manual"

    value = str(value).strip().lower()

    if value == "fixed":
        return "Fixed"

    if value == "formula":
        return "Formula"

    return "Manual"


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
        return None

    return int(number)


def ensure_product_master_tables(conn, cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS product_component_size_lines (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            product_cat TEXT NOT NULL,
            product_code TEXT NOT NULL,
            component TEXT NOT NULL,
            line_no INTEGER NOT NULL,
            width NUMERIC,
            thickness NUMERIC,
            quantity INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS product_input_dimensions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            product_cat TEXT NOT NULL,
            product_code TEXT NOT NULL,
            dimension_key TEXT NOT NULL,
            dimension_label TEXT NOT NULL,
            unit TEXT DEFAULT 'mm',
            display_order INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

    conn.commit()


def fetch_component_size_lines(cur, product_cat, product_code, component):
    return fetch_df(
        cur,
        """
        SELECT
            line_no,
            width,
            thickness,
            quantity
        FROM product_component_size_lines
        WHERE product_cat = %s
          AND product_code = %s
          AND component = %s
        ORDER BY line_no
        """,
        (product_cat, product_code, component)
    )


def fetch_product_input_dimensions(cur, product_cat, product_code):
    return fetch_df(
        cur,
        """
        SELECT
            dimension_key,
            dimension_label,
            unit,
            display_order
        FROM product_input_dimensions
        WHERE product_cat = %s
          AND product_code = %s
        ORDER BY display_order
        """,
        (product_cat, product_code)
    )


def get_product_options(cur):
    products_df = get_products(cur)

    return {
        product_label(row): {
            "product_cat": row["product_cat"],
            "product_code": row["product_code"]
        }
        for _, row in products_df.iterrows()
    }


def get_assigned_components(cur, product_cat, product_code):
    return fetch_df(
        cur,
        """
        SELECT DISTINCT component
        FROM product_component_rules
        WHERE product_cat = %s
          AND product_code = %s
        ORDER BY component
        """,
        (product_cat, product_code)
    )


def insert_default_component_rules(cur, product_cat, product_code, component_name):
    attributes = ["Length", "Width", "Thickness"]

    display_order = 1

    for attribute in attributes:
        cur.execute(
            """
            INSERT INTO product_component_rules
            (
                product_cat,
                product_code,
                component,
                attribute,
                "type",
                formula_used,
                quantity,
                fixed_value,
                display_order
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_cat,
                product_code,
                component_name,
                attribute,
                "Manual",
                None,
                None,
                None,
                display_order
            )
        )

        display_order += 1

    cur.execute(
        """
        INSERT INTO product_component_rules
        (
            product_cat,
            product_code,
            component,
            attribute,
            "type",
            formula_used,
            quantity,
            fixed_value,
            display_order
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            product_cat,
            product_code,
            component_name,
            "Quantity",
            "Fixed",
            None,
            1,
            1,
            display_order
        )
    )


def save_product_input_dimensions(conn, cur, product_cat, product_code, dimensions_df):
    rows_to_save = []

    for _, row in dimensions_df.iterrows():
        dimension_key = str(row.get("Dimension Key", "")).strip()
        dimension_label = str(row.get("Label", "")).strip()
        unit = str(row.get("Unit", "mm")).strip() or "mm"

        if not dimension_key and not dimension_label:
            continue

        if not dimension_key or not dimension_label:
            st.warning("Enter both Dimension Key and Label.")
            st.stop()

        rows_to_save.append({
            "dimension_key": dimension_key,
            "dimension_label": dimension_label,
            "unit": unit
        })

    if not rows_to_save:
        rows_to_save = [
            {
                "dimension_key": "opening_width",
                "dimension_label": "Opening Width",
                "unit": "mm"
            },
            {
                "dimension_key": "opening_height",
                "dimension_label": "Opening Height",
                "unit": "mm"
            }
        ]

    cur.execute(
        """
        DELETE FROM product_input_dimensions
        WHERE product_cat = %s
          AND product_code = %s
        """,
        (product_cat, product_code)
    )

    for index, row in enumerate(rows_to_save, start=1):
        cur.execute(
            """
            INSERT INTO product_input_dimensions
            (
                product_cat,
                product_code,
                dimension_key,
                dimension_label,
                unit,
                display_order
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                product_cat,
                product_code,
                row["dimension_key"],
                row["dimension_label"],
                row["unit"],
                index
            )
        )

    conn.commit()


def fetch_product_definition_for_calculator(cur, product_cat, product_code):
    rules_df = fetch_df(
        cur,
        """
        SELECT
            component,
            attribute,
            "type",
            fixed_value,
            formula_used,
            quantity,
            display_order
        FROM product_component_rules
        WHERE product_cat = %s
          AND product_code = %s
        ORDER BY component, display_order
        """,
        (product_cat, product_code)
    )

    size_lines_df = fetch_df(
        cur,
        """
        SELECT
            component,
            line_no,
            width,
            thickness,
            quantity
        FROM product_component_size_lines
        WHERE product_cat = %s
          AND product_code = %s
        ORDER BY component, line_no
        """,
        (product_cat, product_code)
    )

    dimensions_df = fetch_product_input_dimensions(cur, product_cat, product_code)

    return {
        "rules": rules_df,
        "size_lines": size_lines_df,
        "input_dimensions": dimensions_df
    }


def show_product_master(conn, cur):
    st.title("Product Master")

    ensure_product_master_tables(conn, cur)

    attributes = ["Length", "Width", "Thickness"]

    with st.expander("1. Add Product", expanded=True):
        with st.form("add_product_form"):
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                product_cat = st.text_input(
                    "Product Category",
                    placeholder="Door"
                )

            with col2:
                product_code = st.text_input(
                    "Product Code",
                    placeholder="D2-2.1"
                )

            with col3:
                st.write("")
                st.write("")
                submitted = st.form_submit_button("Save Product")

            if submitted:
                product_cat = product_cat.strip()
                product_code = product_code.strip()

                if not product_cat:
                    st.warning("Enter product category.")
                elif not product_code:
                    st.warning("Enter product code.")
                else:
                    cur.execute(
                        """
                        SELECT id
                        FROM products
                        WHERE product_cat = %s
                          AND product_code = %s
                        """,
                        (product_cat, product_code)
                    )

                    if cur.fetchone():
                        st.warning("This product already exists.")
                    else:
                        cur.execute(
                            """
                            INSERT INTO products (product_cat, product_code)
                            VALUES (%s, %s)
                            """,
                            (product_cat, product_code)
                        )

                        conn.commit()

                        new_label = f"{product_cat} - {product_code}"
                        st.session_state["component_product_select"] = new_label
                        st.session_state["define_product_select"] = new_label
                        st.session_state["view_product_select"] = new_label
                        st.session_state["dimension_product_select"] = new_label

                        st.success("Product saved.")
                        st.rerun()

    with st.expander("2. Add Components to Product", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("Add a product first.")
        else:
            product_options = get_product_options(cur)

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="component_product_select"
            )

            selected_cat = product_options[selected_product]["product_cat"]
            selected_code = product_options[selected_product]["product_code"]

            existing_components_df = get_assigned_components(
                cur,
                selected_cat,
                selected_code
            )

            if not existing_components_df.empty:
                st.caption("Components already added")
                st.dataframe(
                    existing_components_df,
                    use_container_width=True,
                    hide_index=True
                )

            blank_rows = pd.DataFrame(
                [{"Component": ""} for _ in range(10)]
            )

            with st.form("bulk_add_components_form"):
                edited_components_df = st.data_editor(
                    blank_rows,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config={
                        "Component": st.column_config.TextColumn(
                            "Component",
                            help="Paste component names here, one per row."
                        )
                    },
                    key=f"component_table_{selected_cat}_{selected_code}"
                )

                submitted = st.form_submit_button("Save Components to Product")

                if submitted:
                    cleaned_components = []

                    for _, row in edited_components_df.iterrows():
                        component_name = str(row.get("Component", "")).strip()

                        if component_name:
                            cleaned_components.append(component_name)

                    cleaned_components = list(dict.fromkeys(cleaned_components))

                    if not cleaned_components:
                        st.warning("Enter at least one component.")
                    else:
                        added_count = 0

                        for component_name in cleaned_components:
                            cur.execute(
                                """
                                INSERT INTO component_library (component_name)
                                VALUES (%s)
                                ON CONFLICT (component_name) DO NOTHING
                                """,
                                (component_name,)
                            )

                            cur.execute(
                                """
                                SELECT id
                                FROM product_component_rules
                                WHERE product_cat = %s
                                  AND product_code = %s
                                  AND component = %s
                                LIMIT 1
                                """,
                                (selected_cat, selected_code, component_name)
                            )

                            if cur.fetchone():
                                continue

                            insert_default_component_rules(
                                cur,
                                selected_cat,
                                selected_code,
                                component_name
                            )

                            added_count += 1

                        conn.commit()
                        st.success(f"{added_count} component(s) added.")
                        st.rerun()

    with st.expander("3. Define Product Input Dimensions", expanded=False):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("Add a product first.")
        else:
            product_options = get_product_options(cur)

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="dimension_product_select"
            )

            selected_cat = product_options[selected_product]["product_cat"]
            selected_code = product_options[selected_product]["product_code"]

            dimensions_df = fetch_product_input_dimensions(
                cur,
                selected_cat,
                selected_code
            )

            if dimensions_df.empty:
                editor_df = pd.DataFrame(
                    [
                        {
                            "Dimension Key": "opening_width",
                            "Label": "Opening Width",
                            "Unit": "mm"
                        },
                        {
                            "Dimension Key": "opening_height",
                            "Label": "Opening Height",
                            "Unit": "mm"
                        }
                    ]
                )
            else:
                editor_df = dimensions_df.rename(
                    columns={
                        "dimension_key": "Dimension Key",
                        "dimension_label": "Label",
                        "unit": "Unit"
                    }
                )[["Dimension Key", "Label", "Unit"]]

            with st.form("product_dimensions_form"):
                edited_dimensions_df = st.data_editor(
                    editor_df,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    key=f"dimension_table_{selected_cat}_{selected_code}"
                )

                submitted = st.form_submit_button("Save Input Dimensions")

                if submitted:
                    save_product_input_dimensions(
                        conn,
                        cur,
                        selected_cat,
                        selected_code,
                        edited_dimensions_df
                    )

                    st.success("Input dimensions saved.")
                    st.rerun()

    with st.expander("4. Define Product Component Attributes", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("Add a product first.")
            return

        product_options = get_product_options(cur)

        selected_product = st.selectbox(
            "Select Product",
            list(product_options.keys()),
            key="define_product_select"
        )

        selected_cat = product_options[selected_product]["product_cat"]
        selected_code = product_options[selected_product]["product_code"]

        assigned_components_df = get_assigned_components(
            cur,
            selected_cat,
            selected_code
        )

        if assigned_components_df.empty:
            st.info("No components added to this product yet.")
            return

        selected_component = st.selectbox(
            "Select Component",
            assigned_components_df["component"].tolist(),
            key=f"define_component_select_{selected_cat}_{selected_code}"
        )

        rules_df = fetch_df(
            cur,
            """
            SELECT
                attribute,
                "type",
                fixed_value,
                formula_used,
                quantity
            FROM product_component_rules
            WHERE product_cat = %s
              AND product_code = %s
              AND component = %s
            ORDER BY display_order
            """,
            (selected_cat, selected_code, selected_component)
        )

        existing_map = {
            row["attribute"]: row
            for _, row in rules_df.iterrows()
        }

        quantity_value = 1

        if "Quantity" in existing_map:
            quantity_row = existing_map["Quantity"]

            if quantity_row["quantity"] is not None:
                quantity_value = int(quantity_row["quantity"])
            elif quantity_row["fixed_value"] is not None:
                quantity_value = int(quantity_row["fixed_value"])

        rule_rows = []

        for attribute in attributes:
            existing = existing_map.get(attribute)

            rule_type = "Manual"
            value = ""

            if existing is not None:
                rule_type = normalize_rule_type(existing["type"])

                if rule_type == "Fixed" and existing["fixed_value"] is not None:
                    value = float(existing["fixed_value"])
                elif rule_type == "Formula" and existing["formula_used"]:
                    value = existing["formula_used"]

            rule_rows.append(
                {
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Value": value
                }
            )

        st.markdown(f"### {selected_component}")

        with st.form(f"attribute_rules_form_{selected_cat}_{selected_code}_{selected_component}"):
            component_qty = st.number_input(
                "Component Quantity",
                min_value=1,
                value=quantity_value,
                step=1
            )

            edited_rules_df = st.data_editor(
                pd.DataFrame(rule_rows),
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Attribute": st.column_config.TextColumn(
                        "Attribute",
                        disabled=True
                    ),
                    "Type": st.column_config.SelectboxColumn(
                        "Type",
                        options=["Manual", "Fixed", "Formula"],
                        required=True
                    ),
                    "Value": st.column_config.TextColumn(
                        "Value",
                        help="For Manual leave blank. For Fixed enter number. For Formula enter expression."
                    )
                },
                key=f"rules_table_{selected_cat}_{selected_code}_{selected_component}"
            )

            existing_size_lines_df = fetch_component_size_lines(
                cur,
                selected_cat,
                selected_code,
                selected_component
            )

            has_existing_size_lines = not existing_size_lines_df.empty

            use_multiple_size_lines = st.checkbox(
                "This component has multiple Width / Thickness / Quantity lines",
                value=has_existing_size_lines,
                key=f"multi_size_{selected_cat}_{selected_code}_{selected_component}"
            )

            edited_size_lines_df = pd.DataFrame()

            if use_multiple_size_lines:
                if has_existing_size_lines:
                    size_editor_df = existing_size_lines_df.rename(
                        columns={
                            "line_no": "Line",
                            "width": "Width",
                            "thickness": "Thickness",
                            "quantity": "Quantity"
                        }
                    )
                else:
                    size_editor_df = pd.DataFrame(
                        [
                            {
                                "Line": 1,
                                "Width": 0,
                                "Thickness": 0,
                                "Quantity": 1
                            },
                            {
                                "Line": 2,
                                "Width": 0,
                                "Thickness": 0,
                                "Quantity": 1
                            }
                        ]
                    )

                edited_size_lines_df = st.data_editor(
                    size_editor_df,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config={
                        "Line": st.column_config.NumberColumn(
                            "Line",
                            min_value=1,
                            step=1
                        ),
                        "Width": st.column_config.NumberColumn(
                            "Width",
                            step=1.0
                        ),
                        "Thickness": st.column_config.NumberColumn(
                            "Thickness",
                            step=1.0
                        ),
                        "Quantity": st.column_config.NumberColumn(
                            "Quantity",
                            min_value=1,
                            step=1
                        )
                    },
                    key=f"size_lines_table_{selected_cat}_{selected_code}_{selected_component}"
                )

            submitted = st.form_submit_button("Save Attribute Rules", type="primary")

            if submitted:
                cleaned_rules = []

                for _, row in edited_rules_df.iterrows():
                    attribute = str(row.get("Attribute", "")).strip()
                    rule_type = normalize_rule_type(row.get("Type", "Manual"))
                    raw_value = row.get("Value", "")

                    fixed_value = None
                    formula_used = None

                    if rule_type == "Fixed":
                        fixed_value = clean_number(raw_value)

                        if fixed_value is None:
                            st.warning(f"Enter fixed value for {attribute}.")
                            st.stop()

                    elif rule_type == "Formula":
                        formula_used = str(raw_value).strip()

                        if not formula_used:
                            st.warning(f"Enter formula for {attribute}.")
                            st.stop()

                    cleaned_rules.append(
                        {
                            "attribute": attribute,
                            "type": rule_type,
                            "fixed_value": fixed_value,
                            "formula_used": formula_used
                        }
                    )

                cleaned_size_lines = []

                if use_multiple_size_lines:
                    for _, row in edited_size_lines_df.iterrows():
                        line_no = clean_int(row.get("Line"))
                        width = clean_number(row.get("Width"))
                        thickness = clean_number(row.get("Thickness"))
                        quantity = clean_int(row.get("Quantity"))

                        if line_no is None:
                            continue

                        if quantity is None or quantity <= 0:
                            st.warning(f"Enter quantity for size line {line_no}.")
                            st.stop()

                        cleaned_size_lines.append(
                            {
                                "line_no": line_no,
                                "width": width,
                                "thickness": thickness,
                                "quantity": quantity
                            }
                        )

                    cleaned_size_lines = sorted(
                        cleaned_size_lines,
                        key=lambda item: item["line_no"]
                    )

                    if not cleaned_size_lines:
                        st.warning("Enter at least one size line.")
                        st.stop()

                cur.execute(
                    """
                    DELETE FROM product_component_rules
                    WHERE product_cat = %s
                      AND product_code = %s
                      AND component = %s
                    """,
                    (selected_cat, selected_code, selected_component)
                )

                cur.execute(
                    """
                    DELETE FROM product_component_size_lines
                    WHERE product_cat = %s
                      AND product_code = %s
                      AND component = %s
                    """,
                    (selected_cat, selected_code, selected_component)
                )

                display_order = 1

                for rule in cleaned_rules:
                    cur.execute(
                        """
                        INSERT INTO product_component_rules
                        (
                            product_cat,
                            product_code,
                            component,
                            attribute,
                            "type",
                            formula_used,
                            quantity,
                            fixed_value,
                            display_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            selected_cat,
                            selected_code,
                            selected_component,
                            rule["attribute"],
                            rule["type"],
                            rule["formula_used"],
                            None,
                            rule["fixed_value"],
                            display_order
                        )
                    )

                    display_order += 1

                cur.execute(
                    """
                    INSERT INTO product_component_rules
                    (
                        product_cat,
                        product_code,
                        component,
                        attribute,
                        "type",
                        formula_used,
                        quantity,
                        fixed_value,
                        display_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        selected_cat,
                        selected_code,
                        selected_component,
                        "Quantity",
                        "Fixed",
                        None,
                        component_qty,
                        component_qty,
                        display_order
                    )
                )

                for line in cleaned_size_lines:
                    cur.execute(
                        """
                        INSERT INTO product_component_size_lines
                        (
                            product_cat,
                            product_code,
                            component,
                            line_no,
                            width,
                            thickness,
                            quantity
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            selected_cat,
                            selected_code,
                            selected_component,
                            line["line_no"],
                            line["width"],
                            line["thickness"],
                            line["quantity"]
                        )
                    )

                conn.commit()
                st.success("Attribute rules saved.")
                st.rerun()

    with st.expander("5. Existing Product Definitions", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("No products found.")
        else:
            product_options = get_product_options(cur)

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="view_product_select"
            )

            selected_cat = product_options[selected_product]["product_cat"]
            selected_code = product_options[selected_product]["product_code"]

            rules_df = fetch_df(
                cur,
                """
                SELECT
                    component,
                    attribute,
                    "type",
                    fixed_value,
                    formula_used,
                    quantity
                FROM product_component_rules
                WHERE product_cat = %s
                  AND product_code = %s
                ORDER BY component, display_order
                """,
                (selected_cat, selected_code)
            )

            size_lines_df = fetch_df(
                cur,
                """
                SELECT
                    component,
                    line_no,
                    width,
                    thickness,
                    quantity
                FROM product_component_size_lines
                WHERE product_cat = %s
                  AND product_code = %s
                ORDER BY component, line_no
                """,
                (selected_cat, selected_code)
            )

            dimensions_df = fetch_product_input_dimensions(
                cur,
                selected_cat,
                selected_code
            )

            if not dimensions_df.empty:
                st.markdown("### Product Input Dimensions")
                st.dataframe(
                    dimensions_df,
                    use_container_width=True,
                    hide_index=True
                )

            if rules_df.empty:
                st.info("No product definitions found.")
            else:
                display_rows = []

                for component in sorted(rules_df["component"].unique()):
                    component_rules = rules_df[
                        rules_df["component"] == component
                    ]

                    row_data = {
                        "Component": component,
                        "Quantity": ""
                    }

                    for _, rule in component_rules.iterrows():
                        attribute = rule["attribute"]
                        rule_type = normalize_rule_type(rule["type"])

                        if attribute == "Quantity":
                            if rule["quantity"] is not None:
                                row_data["Quantity"] = rule["quantity"]
                            elif rule["fixed_value"] is not None:
                                row_data["Quantity"] = rule["fixed_value"]
                            continue

                        if rule_type == "Fixed":
                            value = rule["fixed_value"]
                        elif rule_type == "Formula":
                            value = rule["formula_used"]
                        else:
                            value = "Manual"

                        row_data[f"{attribute} Type"] = rule_type
                        row_data[f"{attribute} Value"] = value

                    component_size_lines = size_lines_df[
                        size_lines_df["component"] == component
                    ]

                    row_data["Multiple Size Lines"] = (
                        "Yes" if not component_size_lines.empty else "No"
                    )

                    display_rows.append(row_data)

                display_df = pd.DataFrame(display_rows)

                st.markdown("### Component Rules")
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )

                if not size_lines_df.empty:
                    st.markdown("### Multiple Width / Thickness / Quantity Lines")
                    st.dataframe(
                        size_lines_df,
                        use_container_width=True,
                        hide_index=True
                    )
