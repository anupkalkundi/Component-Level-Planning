import streamlit as st
import pandas as pd


def fetch_data(cur, query, params=None):
    cur.execute(query, params or ())
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return pd.DataFrame(rows, columns=columns)


def show_product_master(conn, cur):
    st.title("Product Master")

    # =====================================================
    # 1. COMPONENT LIBRARY CRUD
    # =====================================================
    with st.expander("1. Component Library CRUD", expanded=True):
        st.subheader("Component Library")

        components_df = fetch_data(
            cur,
            """
            SELECT *
            FROM component_library
            ORDER BY id DESC
            """
        )

        st.dataframe(components_df, use_container_width=True)

        st.markdown("### Add Component")

        with st.form("add_component_form"):
            component_name = st.text_input("Component Name")
            attribute = st.text_input("Attribute")

            submitted = st.form_submit_button("Add Component")

            if submitted:
                if component_name.strip() == "" or attribute.strip() == "":
                    st.warning("Please enter component name and attribute.")
                else:
                    cur.execute(
                        """
                        INSERT INTO component_library
                            (component_name, attribute)
                        VALUES
                            (%s, %s)
                        """,
                        (component_name, attribute)
                    )
                    conn.commit()
                    st.success("Component added successfully.")
                    st.rerun()

        st.markdown("### Update Component")

        if not components_df.empty:
            component_options = {
                f"{row['id']} - {row['component_name']} - {row['attribute']}": row["id"]
                for _, row in components_df.iterrows()
            }

            selected_component = st.selectbox(
                "Select Component to Update",
                list(component_options.keys())
            )

            selected_component_id = component_options[selected_component]
            selected_row = components_df[
                components_df["id"] == selected_component_id
            ].iloc[0]

            with st.form("update_component_form"):
                updated_component_name = st.text_input(
                    "Updated Component Name",
                    value=str(selected_row["component_name"])
                )
                updated_attribute = st.text_input(
                    "Updated Attribute",
                    value=str(selected_row["attribute"])
                )

                update_submitted = st.form_submit_button("Update Component")

                if update_submitted:
                    cur.execute(
                        """
                        UPDATE component_library
                        SET component_name = %s,
                            attribute = %s
                        WHERE id = %s
                        """,
                        (
                            updated_component_name,
                            updated_attribute,
                            selected_component_id
                        )
                    )
                    conn.commit()
                    st.success("Component updated successfully.")
                    st.rerun()

        else:
            st.info("No components available to update.")

        st.markdown("### Delete Component")

        if not components_df.empty:
            component_options_delete = {
                f"{row['id']} - {row['component_name']} - {row['attribute']}": row["id"]
                for _, row in components_df.iterrows()
            }

            selected_delete_component = st.selectbox(
                "Select Component to Delete",
                list(component_options_delete.keys())
            )

            if st.button("Delete Component"):
                cur.execute(
                    """
                    DELETE FROM component_library
                    WHERE id = %s
                    """,
                    (component_options_delete[selected_delete_component],)
                )
                conn.commit()
                st.success("Component deleted successfully.")
                st.rerun()

        else:
            st.info("No components available to delete.")

    # =====================================================
    # 2. PRODUCT CREATION
    # =====================================================
    with st.expander("2. Product Creation", expanded=True):
        st.subheader("Products")

        products_df = fetch_data(
            cur,
            """
            SELECT *
            FROM products
            ORDER BY id DESC
            """
        )

        st.dataframe(products_df, use_container_width=True)

        with st.form("create_product_form"):
            product_name = st.text_input("Product Name")
            product_description = st.text_area("Product Description")

            product_submitted = st.form_submit_button("Create Product")

            if product_submitted:
                if product_name.strip() == "":
                    st.warning("Please enter product name.")
                else:
                    cur.execute(
                        """
                        INSERT INTO products
                            (product_name, product_description)
                        VALUES
                            (%s, %s)
                        """,
                        (product_name, product_description)
                    )
                    conn.commit()
                    st.success("Product created successfully.")
                    st.rerun()

    # =====================================================
    # 3. PRODUCT DEFINITION
    # =====================================================
    with st.expander("3. Product Definition", expanded=True):
        st.subheader("Define Product Rules")

        products_df = fetch_data(
            cur,
            """
            SELECT *
            FROM products
            ORDER BY product_name
            """
        )

        components_df = fetch_data(
            cur,
            """
            SELECT *
            FROM component_library
            ORDER BY component_name, attribute
            """
        )

        if products_df.empty:
            st.info("Create a product first.")
        elif components_df.empty:
            st.info("Create a component first.")
        else:
            product_options = {
                row["product_name"]: row["id"]
                for _, row in products_df.iterrows()
            }

            component_options = {
                f"{row['component_name']} - {row['attribute']}": row["id"]
                for _, row in components_df.iterrows()
            }

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys())
            )

            selected_component = st.selectbox(
                "Select Component",
                list(component_options.keys())
            )

            selected_component_id = component_options[selected_component]

            selected_component_row = components_df[
                components_df["id"] == selected_component_id
            ].iloc[0]

            selected_attribute = st.selectbox(
                "Select Attribute",
                [selected_component_row["attribute"]]
            )

            rule_type = st.selectbox(
                "Select Type",
                ["Formula", "Fixed", "Manual"]
            )

            formula = None
            fixed_value = None

            if rule_type == "Formula":
                formula = st.text_area("Formula")

            elif rule_type == "Fixed":
                fixed_value = st.number_input("Fixed Value", value=0.0)

            elif rule_type == "Manual":
                st.info("Manual value will be entered during calculation.")

            if st.button("Save Product Rule"):
                if rule_type == "Formula" and not formula:
                    st.warning("Please enter formula.")
                else:
                    cur.execute(
                        """
                        INSERT INTO product_component_rules
                            (
                                product_id,
                                component_id,
                                attribute,
                                rule_type,
                                formula,
                                fixed_value
                            )
                        VALUES
                            (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            product_options[selected_product],
                            selected_component_id,
                            selected_attribute,
                            rule_type,
                            formula,
                            fixed_value
                        )
                    )
                    conn.commit()
                    st.success("Product rule saved successfully.")
                    st.rerun()

    # =====================================================
    # 4. DISPLAY EXISTING RULES
    # =====================================================
    with st.expander("4. Existing Rules", expanded=True):
        st.subheader("Existing Rules for Product")

        products_df = fetch_data(
            cur,
            """
            SELECT *
            FROM products
            ORDER BY product_name
            """
        )

        if products_df.empty:
            st.info("No products found.")
        else:
            product_options = {
                row["product_name"]: row["id"]
                for _, row in products_df.iterrows()
            }

            selected_product_rules = st.selectbox(
                "Select Product to View Rules",
                list(product_options.keys())
            )

            rules_df = fetch_data(
                cur,
                """
                SELECT
                    pcr.id,
                    p.product_name,
                    cl.component_name,
                    pcr.attribute,
                    pcr.rule_type,
                    pcr.formula,
                    pcr.fixed_value
                FROM product_component_rules pcr
                LEFT JOIN products p
                    ON p.id = pcr.product_id
                LEFT JOIN component_library cl
                    ON cl.id = pcr.component_id
                WHERE pcr.product_id = %s
                ORDER BY pcr.id DESC
                """,
                (product_options[selected_product_rules],)
            )

            st.dataframe(rules_df, use_container_width=True)
