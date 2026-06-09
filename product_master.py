import streamlit as st
import pandas as pd


# =========================================================
# HELPERS
# =========================================================
def fetch_df(cur, query, params=None):
    cur.execute(query, params or ())
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    return pd.DataFrame(rows, columns=cols)


# =========================================================
# PRODUCT MASTER PAGE
# =========================================================
def show_product_master(conn, cur):

    st.title("Product Master")

    # =====================================================
    # 1. COMPONENT LIBRARY CRUD
    # =====================================================
    with st.expander("1. Component Library", expanded=True):

        st.subheader("Component Library")

        components_df = fetch_df(
            cur,
            """
            SELECT id, component_name
            FROM component_library
            ORDER BY component_name
            """
        )

        st.dataframe(components_df, use_container_width=True)

        st.markdown("### Add Component")

        with st.form("add_component_form"):
            component_name = st.text_input(
                "Component Name",
                placeholder="Example: Frame Vertical"
            )

            add_component = st.form_submit_button("Add Component")

            if add_component:
                if component_name.strip() == "":
                    st.warning("Please enter component name.")
                else:
                    cur.execute(
                        """
                        INSERT INTO component_library (component_name)
                        VALUES (%s)
                        """,
                        (component_name.strip(),)
                    )
                    conn.commit()
                    st.success("Component added successfully.")
                    st.rerun()

        st.markdown("### Delete Component")

        if not components_df.empty:
            component_options = {
                row["component_name"]: row["id"]
                for _, row in components_df.iterrows()
            }

            delete_component_name = st.selectbox(
                "Select Component to Delete",
                list(component_options.keys())
            )

            if st.button("Delete Component"):
                cur.execute(
                    """
                    DELETE FROM component_library
                    WHERE id = %s
                    """,
                    (component_options[delete_component_name],)
                )
                conn.commit()
                st.success("Component deleted successfully.")
                st.rerun()
        else:
            st.info("No components available.")

    # =====================================================
    # 2. PRODUCT CREATION
    # =====================================================
    with st.expander("2. Product Creation", expanded=True):

        st.subheader("Create Product")

        products_df = fetch_df(
            cur,
            """
            SELECT id, product_name, category
            FROM products
            ORDER BY product_name
            """
        )

        st.dataframe(products_df, use_container_width=True)

        with st.form("create_product_form"):
            product_name = st.text_input(
                "Product Name",
                placeholder="Example: D1-1.1"
            )

            category = st.text_input(
                "Category",
                placeholder="Example: Door"
            )

            create_product = st.form_submit_button("Create Product")

            if create_product:
                if product_name.strip() == "":
                    st.warning("Please enter product name.")
                elif category.strip() == "":
                    st.warning("Please enter category.")
                else:
                    cur.execute(
                        """
                        INSERT INTO products (product_name, category)
                        VALUES (%s, %s)
                        """,
                        (product_name.strip(), category.strip())
                    )
                    conn.commit()
                    st.success("Product created successfully.")
                    st.rerun()

    # =====================================================
    # 3. PRODUCT DEFINITION
    # =====================================================
    with st.expander("3. Product Definition", expanded=True):

        st.subheader("Define Component Attributes")

        products_df = fetch_df(
            cur,
            """
            SELECT id, product_name, category
            FROM products
            ORDER BY product_name
            """
        )

        components_df = fetch_df(
            cur,
            """
            SELECT id, component_name
            FROM component_library
            ORDER BY component_name
            """
        )

        if products_df.empty:
            st.info("Please create a product first.")
            return

        if components_df.empty:
            st.info("Please add components first.")
            return

        product_options = {
            f"{row['product_name']} - {row['category']}": row["id"]
            for _, row in products_df.iterrows()
        }

        component_options = {
            row["component_name"]: row["id"]
            for _, row in components_df.iterrows()
        }

        selected_product_label = st.selectbox(
            "Product",
            list(product_options.keys())
        )

        selected_component_label = st.selectbox(
            "Component",
            list(component_options.keys())
        )

        attribute = st.selectbox(
            "Attribute",
            [
                "Length",
                "Width",
                "Thickness",
                "Quantity"
            ]
        )

        attribute_type = st.selectbox(
            "Attribute Type",
            [
                "Fixed",
                "Manual",
                "Formula"
            ]
        )

        fixed_value = None
        formula = None

        if attribute_type == "Fixed":
            fixed_value = st.number_input(
                "Enter Fixed Value",
                value=0.0,
                step=1.0
            )

        elif attribute_type == "Manual":
            st.info("Manual value will be entered in calculator.")

        elif attribute_type == "Formula":
            formula = st.text_area(
                "Enter Formula Expression",
                placeholder=(
                    "Examples:\n"
                    "opening_length\n"
                    "opening_width - 40\n"
                    "shutter_width / 2"
                )
            )

        if st.button("Save Product Definition"):
            if attribute_type == "Formula" and not formula:
                st.warning("Please enter formula expression.")
            else:
                cur.execute(
                    """
                    INSERT INTO product_component_rules
                    (
                        product_id,
                        component_id,
                        attribute_name,
                        attribute_type,
                        fixed_value,
                        formula
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        product_options[selected_product_label],
                        component_options[selected_component_label],
                        attribute,
                        attribute_type,
                        fixed_value,
                        formula
                    )
                )

                conn.commit()
                st.success("Product definition saved successfully.")
                st.rerun()

    # =====================================================
    # 4. DISPLAY EXISTING RULES
    # =====================================================
    with st.expander("4. Existing Product Rules", expanded=True):

        st.subheader("Existing Rules")

        products_df = fetch_df(
            cur,
            """
            SELECT id, product_name, category
            FROM products
            ORDER BY product_name
            """
        )

        if products_df.empty:
            st.info("No products found.")
        else:
            product_options = {
                f"{row['product_name']} - {row['category']}": row["id"]
                for _, row in products_df.iterrows()
            }

            selected_product_label = st.selectbox(
                "Select Product to View Rules",
                list(product_options.keys()),
                key="view_rules_product"
            )

            rules_df = fetch_df(
                cur,
                """
                SELECT
                    p.product_name,
                    p.category,
                    c.component_name,
                    r.attribute_name,
                    r.attribute_type,
                    r.fixed_value,
                    r.formula
                FROM product_component_rules r
                JOIN products p
                    ON p.id = r.product_id
                JOIN component_library c
                    ON c.id = r.component_id
                WHERE r.product_id = %s
                ORDER BY c.component_name, r.attribute_name
                """,
                (product_options[selected_product_label],)
            )

            st.dataframe(rules_df, use_container_width=True)
