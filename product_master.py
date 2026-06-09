import streamlit as st
import pandas as pd


def fetch_df(cur, query, params=None):
    cur.execute(query, params or ())
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return pd.DataFrame(rows, columns=columns)


def show_product_master(conn, cur):
    st.title("Product Master")

    attributes = ["Length", "Width", "Thickness", "Quantity"]
    rule_types = ["Manual", "Fixed", "Formula"]

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
                    placeholder="D1-1.1"
                )

            with col3:
                st.write("")
                st.write("")
                submitted = st.form_submit_button("Save Product")

            if submitted:
                if not product_cat.strip():
                    st.warning("Enter product category.")
                elif not product_code.strip():
                    st.warning("Enter product code.")
                else:
                    cur.execute(
                        """
                        INSERT INTO products (product_cat, product_code)
                        VALUES (%s, %s)
                        """,
                        (product_cat.strip(), product_code.strip())
                    )
                    conn.commit()
                    st.success("Product saved.")
                    st.rerun()

    # =====================================================
    # 2. BULK ADD COMPONENTS
    # =====================================================
    with st.expander("2. Add Components", expanded=True):
        st.subheader("Bulk Add Components")

        row_count = st.number_input(
            "Number of component rows",
            min_value=1,
            max_value=50,
            value=5,
            step=1
        )

        with st.form("bulk_component_form"):
            component_rows = []

            for i in range(int(row_count)):
                component_name = st.text_input(
                    f"Component {i + 1}",
                    placeholder="Example: Frame Vertical",
                    key=f"component_bulk_{i}"
                )
                component_rows.append(component_name)

            submitted = st.form_submit_button("Save Components")

            if submitted:
                cleaned_components = [
                    name.strip()
                    for name in component_rows
                    if name and name.strip()
                ]

                if not cleaned_components:
                    st.warning("Enter at least one component.")
                else:
                    for component_name in cleaned_components:
                        cur.execute(
                            """
                            INSERT INTO component_library (component_name)
                            VALUES (%s)
                            ON CONFLICT (component_name) DO NOTHING
                            """,
                            (component_name,)
                        )

                    conn.commit()
                    st.success(f"{len(cleaned_components)} component(s) saved.")
                    st.rerun()

        with st.expander("View Existing Components"):
            components_df = fetch_df(
                cur,
                """
                SELECT component_name
                FROM component_library
                ORDER BY component_name
                """
            )
            st.dataframe(components_df, use_container_width=True, hide_index=True)

    # =====================================================
    # 3. DEFINE PRODUCT COMPONENTS
    # =====================================================
    with st.expander("3. Define Product Components", expanded=True):
        products_df = fetch_df(
            cur,
            """
            SELECT product_cat, product_code
            FROM products
            ORDER BY product_cat, product_code
            """
        )

        components_df = fetch_df(
            cur,
            """
            SELECT component_name
            FROM component_library
            ORDER BY component_name
            """
        )

        if products_df.empty:
            st.info("Add a product first.")
            return

        if components_df.empty:
            st.info("Add components first.")
            return

        product_options = {
            f"{row['product_cat']} - {row['product_code']}": {
                "product_cat": row["product_cat"],
                "product_code": row["product_code"]
            }
            for _, row in products_df.iterrows()
        }

        selected_product_label = st.selectbox(
            "Select Product",
            list(product_options.keys())
        )

        selected_product_cat = product_options[selected_product_label]["product_cat"]
        selected_product_code = product_options[selected_product_label]["product_code"]

        component_list = components_df["component_name"].tolist()

        selected_components = st.multiselect(
            "Select Components for this Product",
            component_list,
            placeholder="Choose one or more components"
        )

        if not selected_components:
            st.info("Select components to define attributes.")
        else:
            existing_rules_df = fetch_df(
                cur,
                """
                SELECT
                    component,
                    attribute,
                    type,
                    fixed_value,
                    formula_used,
                    quantity,
                    display_order
                FROM product_component_rules
                WHERE product_cat = %s
                  AND product_code = %s
                """,
                (selected_product_cat, selected_product_code)
            )

            existing_map = {}
            for _, row in existing_rules_df.iterrows():
                existing_map[(row["component"], row["attribute"])] = row

            editor_rows = []

            for component_index, component in enumerate(selected_components):
                for attribute_index, attribute in enumerate(attributes):
                    existing = existing_map.get((component, attribute))

                    if existing is not None:
                        editor_rows.append({
                            "Component": component,
                            "Attribute": attribute,
                            "Type": existing["type"],
                            "Fixed Value": existing["fixed_value"],
                            "Formula": existing["formula_used"] or "",
                            "Quantity": existing["quantity"],
                            "Display Order": existing["display_order"] or component_index + 1
                        })
                    else:
                        editor_rows.append({
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "Manual",
                            "Fixed Value": None,
                            "Formula": "",
                            "Quantity": 1 if attribute == "Quantity" else None,
                            "Display Order": component_index + 1
                        })

            rules_input_df = pd.DataFrame(editor_rows)

            edited_df = st.data_editor(
                rules_input_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Component": st.column_config.TextColumn(
                        "Component",
                        disabled=True
                    ),
                    "Attribute": st.column_config.TextColumn(
                        "Attribute",
                        disabled=True
                    ),
                    "Type": st.column_config.SelectboxColumn(
                        "Type",
                        options=rule_types,
                        required=True
                    ),
                    "Fixed Value": st.column_config.NumberColumn(
                        "Fixed Value",
                        step=1.0
                    ),
                    "Formula": st.column_config.TextColumn(
                        "Formula",
                        help="Use only when Type is Formula. Example: opening_width - 40"
                    ),
                    "Quantity": st.column_config.NumberColumn(
                        "Quantity",
                        min_value=1,
                        step=1
                    ),
                    "Display Order": st.column_config.NumberColumn(
                        "Order",
                        min_value=1,
                        step=1
                    )
                }
            )

            if st.button("Save Product Definition", type="primary"):
                for _, row in edited_df.iterrows():
                    rule_type = row["Type"]
                    formula = str(row["Formula"]).strip() if pd.notna(row["Formula"]) else ""
                    fixed_value = row["Fixed Value"]

                    if rule_type == "Formula" and not formula:
                        st.warning(
                            f"Enter formula for {row['Component']} - {row['Attribute']}."
                        )
                        st.stop()

                    if rule_type == "Fixed" and pd.isna(fixed_value):
                        st.warning(
                            f"Enter fixed value for {row['Component']} - {row['Attribute']}."
                        )
                        st.stop()

                for component in selected_components:
                    cur.execute(
                        """
                        DELETE FROM product_component_rules
                        WHERE product_cat = %s
                          AND product_code = %s
                          AND component = %s
                        """,
                        (
                            selected_product_cat,
                            selected_product_code,
                            component
                        )
                    )

                for _, row in edited_df.iterrows():
                    rule_type = row["Type"]
                    attribute = row["Attribute"]

                    fixed_value = None
                    formula_used = None
                    quantity = None

                    if rule_type == "Fixed":
                        fixed_value = row["Fixed Value"]

                    if rule_type == "Formula":
                        formula_used = str(row["Formula"]).strip()

                    if attribute == "Quantity":
                        if rule_type == "Fixed":
                            quantity = int(row["Fixed Value"])
                        elif pd.notna(row["Quantity"]):
                            quantity = int(row["Quantity"])

                    display_order = 1
                    if pd.notna(row["Display Order"]):
                        display_order = int(row["Display Order"])

                    cur.execute(
                        """
                        INSERT INTO product_component_rules
                        (
                            product_cat,
                            product_code,
                            component,
                            attribute,
                            type,
                            formula_used,
                            quantity,
                            fixed_value,
                            display_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            selected_product_cat,
                            selected_product_code,
                            row["Component"],
                            attribute,
                            rule_type,
                            formula_used,
                            quantity,
                            fixed_value,
                            display_order
                        )
                    )

                conn.commit()
                st.success("Product definition saved.")
                st.rerun()

    # =====================================================
    # 4. EXISTING PRODUCT DEFINITIONS
    # =====================================================
    with st.expander("4. Existing Product Definitions", expanded=True):
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
        else:
            product_options = {
                f"{row['product_cat']} - {row['product_code']}": {
                    "product_cat": row["product_cat"],
                    "product_code": row["product_code"]
                }
                for _, row in products_df.iterrows()
            }

            selected_view_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="view_product_definition"
            )

            view_product_cat = product_options[selected_view_product]["product_cat"]
            view_product_code = product_options[selected_view_product]["product_code"]

            rules_df = fetch_df(
                cur,
                """
                SELECT
                    component,
                    attribute,
                    type,
                    fixed_value,
                    formula_used,
                    quantity,
                    display_order
                FROM product_component_rules
                WHERE product_cat = %s
                  AND product_code = %s
                ORDER BY display_order, component, attribute
                """,
                (view_product_cat, view_product_code)
            )

            st.dataframe(rules_df, use_container_width=True, hide_index=True)
