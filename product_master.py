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
                product_cat = st.text_input("Product Category", placeholder="Door")

            with col2:
                product_code = st.text_input("Product Code", placeholder="D1-1.2")

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
                        SELECT id
                        FROM products
                        WHERE product_cat = %s
                          AND product_code = %s
                        """,
                        (product_cat.strip(), product_code.strip())
                    )

                    if cur.fetchone():
                        st.warning("This product already exists.")
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
                "Select Product for Components",
                list(product_options.keys()),
                key="component_product_select"
            )

            selected_cat = product_options[selected_product]["product_cat"]
            selected_code = product_options[selected_product]["product_code"]

            st.markdown(f"### Components for: `{selected_cat} - {selected_code}`")

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
                st.dataframe(
                    existing_components_df,
                    use_container_width=True,
                    hide_index=True
                )

            row_count = st.number_input(
                "How many components do you want to add?",
                min_value=1,
                max_value=50,
                value=5,
                step=1
            )

            component_input_df = pd.DataFrame({
                "Component": ["" for _ in range(int(row_count))]
            })

            edited_components = st.data_editor(
                component_input_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Component": st.column_config.TextColumn(
                        "Component Name",
                        required=False,
                        help="Example: Frame Vertical, Flush Shutter"
                    )
                },
                key="bulk_product_components_editor"
            )

            if st.button("Save Components to Product", type="primary"):
                component_names = []

                for value in edited_components["Component"].tolist():
                    if value and str(value).strip():
                        component_names.append(str(value).strip())

                component_names = list(dict.fromkeys(component_names))

                if not component_names:
                    st.warning("Enter at least one component.")
                else:
                    added_count = 0

                    for component_name in component_names:
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
                                    1 if attribute == "Quantity" else None,
                                    None,
                                    display_order
                                )
                            )
                            display_order += 1

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
            "Select Product Component",
            assigned_components_df["component"].tolist(),
            key="define_component_select"
        )

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
              AND component = %s
            ORDER BY display_order
            """,
            (selected_cat, selected_code, selected_component)
        )

        existing_map = {
            row["attribute"]: row
            for _, row in rules_df.iterrows()
        }

        editor_rows = []

        for index, attribute in enumerate(attributes, start=1):
            existing = existing_map.get(attribute)

            editor_rows.append({
                "Attribute": attribute,
                "Type": existing["type"] if existing is not None else "Manual",
                "Fixed Value": existing["fixed_value"] if existing is not None else None,
                "Formula": existing["formula_used"] if existing is not None and existing["formula_used"] else "",
                "Quantity": existing["quantity"] if existing is not None else (1 if attribute == "Quantity" else None),
                "Display Order": existing["display_order"] if existing is not None else index
            })

        edit_df = pd.DataFrame(editor_rows)

        edited_df = st.data_editor(
            edit_df,
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
                    options=rule_types,
                    required=True
                ),
                "Fixed Value": st.column_config.NumberColumn(
                    "Fixed Value",
                    step=1.0
                ),
                "Formula": st.column_config.TextColumn(
                    "Formula",
                    help="Example: opening_width - 40"
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
            },
            key=f"rules_editor_{selected_cat}_{selected_code}_{selected_component}"
        )

        if st.button("Save Attribute Rules", type="primary"):
            for _, row in edited_df.iterrows():
                rule_type = row["Type"]
                attribute = row["Attribute"]
                formula = str(row["Formula"]).strip() if pd.notna(row["Formula"]) else ""
                fixed_value = row["Fixed Value"]

                if rule_type == "Formula" and not formula:
                    st.warning(f"Enter formula for {selected_component} - {attribute}.")
                    st.stop()

                if rule_type == "Fixed" and pd.isna(fixed_value):
                    st.warning(f"Enter fixed value for {selected_component} - {attribute}.")
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

                if attribute == "Quantity" and pd.notna(row["Quantity"]):
                    quantity = int(row["Quantity"])

                display_order = int(row["Display Order"]) if pd.notna(row["Display Order"]) else 1

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
                        rule_type,
                        formula_used,
                        quantity,
                        fixed_value,
                        display_order
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
                    quantity,
                    display_order
                FROM product_component_rules
                WHERE product_cat = %s
                  AND product_code = %s
                ORDER BY component, display_order
                """,
                (selected_cat, selected_code)
            )

            st.dataframe(rules_df, use_container_width=True, hide_index=True)
