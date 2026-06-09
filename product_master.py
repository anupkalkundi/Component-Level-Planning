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


def ensure_component_size_lines_table(conn, cur):
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


def show_product_master(conn, cur):
    st.title("Product Master")

    ensure_component_size_lines_table(conn, cur)

    attributes = ["Length", "Width", "Thickness"]

    # =====================================================
    # 1. ADD PRODUCT
    # =====================================================
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
                    placeholder="D1-1.2"
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

                        st.success("Product saved.")
                        st.rerun()

    # =====================================================
    # 2. ADD COMPONENTS TO SELECTED PRODUCT
    # =====================================================
    with st.expander("2. Add Components to Product", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("Add a product first.")
        else:
            product_options = {
                product_label(row): {
                    "product_cat": row["product_cat"],
                    "product_code": row["product_code"]
                }
                for _, row in products_df.iterrows()
            }

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="component_product_select"
            )

            selected_cat = product_options[selected_product]["product_cat"]
            selected_code = product_options[selected_product]["product_code"]

            st.markdown(f"### Add components for `{selected_cat} - {selected_code}`")

            existing_components_df = fetch_df(
                cur,
                """
                SELECT DISTINCT component
                FROM product_component_rules
                WHERE product_cat = %s
                  AND product_code = %s
                ORDER BY component
                """,
                (selected_cat, selected_code)
            )

            if not existing_components_df.empty:
                st.caption("Components already added to this product")
                st.dataframe(
                    existing_components_df,
                    use_container_width=True,
                    hide_index=True
                )

            row_count = st.number_input(
                "Number of component rows",
                min_value=1,
                max_value=50,
                value=5,
                step=1
            )

            with st.form("bulk_add_components_form"):
                component_names = []

                for i in range(int(row_count)):
                    component_name = st.text_input(
                        f"Component {i + 1}",
                        placeholder="Example: Frame Vertical",
                        key=f"component_row_{i}"
                    )
                    component_names.append(component_name)

                submitted = st.form_submit_button("Save Components to Product")

                if submitted:
                    cleaned_components = []

                    for name in component_names:
                        if name and name.strip():
                            cleaned_components.append(name.strip())

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
                                        selected_cat,
                                        selected_code,
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
                                    selected_cat,
                                    selected_code,
                                    component_name,
                                    "Quantity",
                                    "Fixed",
                                    None,
                                    1,
                                    1,
                                    display_order
                                )
                            )

                            added_count += 1

                        conn.commit()
                        st.success(f"{added_count} component(s) added to {selected_code}.")
                        st.rerun()

    # =====================================================
    # 3. DEFINE PRODUCT COMPONENT ATTRIBUTES
    # =====================================================
    with st.expander("3. Define Product Component Attributes", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("Add a product first.")
            return

        product_options = {
            product_label(row): {
                "product_cat": row["product_cat"],
                "product_code": row["product_code"]
            }
            for _, row in products_df.iterrows()
        }

        selected_product = st.selectbox(
            "Select Product",
            list(product_options.keys()),
            key="define_product_select"
        )

        selected_cat = product_options[selected_product]["product_cat"]
        selected_code = product_options[selected_product]["product_code"]

        assigned_components_df = fetch_df(
            cur,
            """
            SELECT DISTINCT component
            FROM product_component_rules
            WHERE product_cat = %s
              AND product_code = %s
            ORDER BY component
            """,
            (selected_cat, selected_code)
        )

        if assigned_components_df.empty:
            st.info("No components added to this product yet.")
            return

        selected_component = st.selectbox(
            "Select Component",
            assigned_components_df["component"].tolist(),
            key="define_component_select"
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

        st.markdown(f"### `{selected_component}`")

        component_qty = st.number_input(
            "Component Quantity",
            min_value=1,
            value=quantity_value,
            step=1
        )

        st.markdown("### Length / Width / Thickness")

        attribute_rules = {}

        for attribute in attributes:
            existing = existing_map.get(attribute)

            existing_type = "Manual"
            existing_fixed_value = 0.0
            existing_formula = ""

            if existing is not None:
                existing_type = normalize_rule_type(existing["type"])

                if existing["fixed_value"] is not None:
                    existing_fixed_value = float(existing["fixed_value"])

                if existing["formula_used"]:
                    existing_formula = existing["formula_used"]

            st.markdown(f"#### {attribute}")

            col1, col2 = st.columns([1, 3])

            with col1:
                selected_type = st.selectbox(
                    "Type",
                    ["Manual", "Fixed", "Formula"],
                    index=["Manual", "Fixed", "Formula"].index(existing_type),
                    key=f"{selected_cat}_{selected_code}_{selected_component}_{attribute}_type"
                )

            fixed_value = None
            formula_used = None

            with col2:
                if selected_type == "Fixed":
                    fixed_value = st.number_input(
                        "Fixed Value",
                        value=existing_fixed_value,
                        step=1.0,
                        key=f"{selected_cat}_{selected_code}_{selected_component}_{attribute}_fixed"
                    )

                elif selected_type == "Formula":
                    formula_used = st.text_input(
                        "Formula",
                        value=existing_formula,
                        placeholder="Example: opening_width - 40",
                        key=f"{selected_cat}_{selected_code}_{selected_component}_{attribute}_formula"
                    )

                else:
                    st.text_input(
                        "Manual",
                        value="Entered in calculator",
                        disabled=True,
                        key=f"{selected_cat}_{selected_code}_{selected_component}_{attribute}_manual"
                    )

            attribute_rules[attribute] = {
                "type": selected_type,
                "fixed_value": fixed_value,
                "formula_used": formula_used
            }

        # =====================================================
        # EXTRA OPTION ADDED ONLY HERE
        # =====================================================
        st.markdown("### Multiple Width / Thickness / Quantity Lines")

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
            key=f"{selected_cat}_{selected_code}_{selected_component}_multi_size_enabled"
        )

        size_lines = []

        if use_multiple_size_lines:
            existing_line_count = len(existing_size_lines_df) if has_existing_size_lines else 2

            line_count = st.number_input(
                "Number of size lines",
                min_value=2,
                max_value=10,
                value=max(2, existing_line_count),
                step=1,
                key=f"{selected_cat}_{selected_code}_{selected_component}_size_line_count"
            )

            existing_lines_map = {}

            if has_existing_size_lines:
                for _, line in existing_size_lines_df.iterrows():
                    existing_lines_map[int(line["line_no"])] = line

            for line_no in range(1, int(line_count) + 1):
                existing_line = existing_lines_map.get(line_no)

                default_width = 0.0
                default_thickness = 0.0
                default_quantity = 0

                if existing_line is not None:
                    if existing_line["width"] is not None:
                        default_width = float(existing_line["width"])
                    if existing_line["thickness"] is not None:
                        default_thickness = float(existing_line["thickness"])
                    if existing_line["quantity"] is not None:
                        default_quantity = int(existing_line["quantity"])

                st.markdown(f"#### Line {line_no}")

                col1, col2, col3 = st.columns(3)

                with col1:
                    width = st.number_input(
                        "Width",
                        value=default_width,
                        step=1.0,
                        key=f"{selected_cat}_{selected_code}_{selected_component}_line_{line_no}_width"
                    )

                with col2:
                    thickness = st.number_input(
                        "Thickness",
                        value=default_thickness,
                        step=1.0,
                        key=f"{selected_cat}_{selected_code}_{selected_component}_line_{line_no}_thickness"
                    )

                with col3:
                    quantity = st.number_input(
                        "Quantity",
                        min_value=0,
                        value=default_quantity,
                        step=1,
                        key=f"{selected_cat}_{selected_code}_{selected_component}_line_{line_no}_quantity"
                    )

                size_lines.append({
                    "line_no": line_no,
                    "width": width,
                    "thickness": thickness,
                    "quantity": quantity,
                })

        if st.button("Save Attribute Rules", type="primary"):
            for attribute, values in attribute_rules.items():
                if values["type"] == "Formula" and not values["formula_used"]:
                    st.warning(f"Enter formula for {selected_component} - {attribute}.")
                    st.stop()

            if use_multiple_size_lines:
                for line in size_lines:
                    if line["quantity"] <= 0:
                        st.warning(f"Enter quantity for size line {line['line_no']}.")
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

            for attribute, values in attribute_rules.items():
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
                        attribute,
                        values["type"],
                        values["formula_used"],
                        None,
                        values["fixed_value"],
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

            if use_multiple_size_lines:
                for line in size_lines:
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
                            line["quantity"],
                        )
                    )

            conn.commit()
            st.success("Attribute rules saved.")
            st.rerun()

    # =====================================================
    # 4. EXISTING PRODUCT DEFINITIONS
    # =====================================================
    with st.expander("4. Existing Product Definitions", expanded=True):
        products_df = get_products(cur)

        if products_df.empty:
            st.info("No products found.")
        else:
            product_options = {
                product_label(row): {
                    "product_cat": row["product_cat"],
                    "product_code": row["product_code"]
                }
                for _, row in products_df.iterrows()
            }

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

                        value = ""

                        if rule_type == "Fixed":
                            value = rule["fixed_value"]
                        elif rule_type == "Formula":
                            value = rule["formula_used"]
                        else:
                            value = "Manual"

                        row_data[f"{attribute} Type"] = rule_type
                        row_data[f"{attribute} Value"] = value

                    has_size_lines = not size_lines_df[
                        size_lines_df["component"] == component
                    ].empty

                    row_data["Multiple Size Lines"] = "Yes" if has_size_lines else "No"

                    display_rows.append(row_data)

                display_df = pd.DataFrame(display_rows)

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
