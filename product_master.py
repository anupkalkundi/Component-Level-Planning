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

    # =====================================================
    # 1. ADD PRODUCT
    # =====================================================
    with st.expander("1. Add Product", expanded=True):
        st.subheader("Add Product")

        products_df = fetch_df(
            cur,
            """
            SELECT id, product_cat, product_code, created_at
            FROM products
            ORDER BY id DESC
            """
        )

        st.dataframe(products_df, use_container_width=True, hide_index=True)

        with st.form("add_product_form"):
            product_cat = st.text_input(
                "Product Category",
                placeholder="Example: Door"
            )

            product_code = st.text_input(
                "Product Code",
                placeholder="Example: D1-1.1"
            )

            submitted = st.form_submit_button("Save Product")

            if submitted:
                if not product_cat.strip():
                    st.warning("Please enter product category.")
                elif not product_code.strip():
                    st.warning("Please enter product code.")
                else:
                    cur.execute(
                        """
                        INSERT INTO products (product_cat, product_code)
                        VALUES (%s, %s)
                        """,
                        (product_cat.strip(), product_code.strip())
                    )
                    conn.commit()
                    st.success("Product saved successfully.")
                    st.rerun()

    # =====================================================
    # 2. COMPONENT LIBRARY
    # =====================================================
    with st.expander("2. Component Library", expanded=True):
        st.subheader("Component Library")

        components_df = fetch_df(
            cur,
            """
            SELECT id, component_name, created_at
            FROM component_library
            ORDER BY component_name
            """
        )

        st.dataframe(components_df, use_container_width=True, hide_index=True)

        with st.form("add_component_form"):
            component_name = st.text_input(
                "Component Name",
                placeholder="Example: Frame Vertical"
            )

            submitted = st.form_submit_button("Add Component")

            if submitted:
                if not component_name.strip():
                    st.warning("Please enter component name.")
                else:
                    cur.execute(
                        """
                        INSERT INTO component_library (component_name)
                        VALUES (%s)
                        ON CONFLICT (component_name) DO NOTHING
                        """,
                        (component_name.strip(),)
                    )
                    conn.commit()
                    st.success("Component added successfully.")
                    st.rerun()

    # =====================================================
    # 3. DEFINE PRODUCT COMPONENTS
    # =====================================================
    with st.expander("3. Define Product Components", expanded=True):
        st.subheader("Define Product Components")

        products_df = fetch_df(
            cur,
            """
            SELECT id, product_cat, product_code
            FROM products
            ORDER BY product_cat, product_code
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
            st.info("Please add a product first.")
            return

        if components_df.empty:
            st.info("Please add components first.")
            return

        product_options = {
            f"{row['product_cat']} - {row['product_code']}": {
                "product_cat": row["product_cat"],
                "product_code": row["product_code"]
            }
            for _, row in products_df.iterrows()
        }

        component_options = {
            row["component_name"]: row["component_name"]
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

        selected_product_cat = product_options[selected_product]["product_cat"]
        selected_product_code = product_options[selected_product]["product_code"]
        selected_component_name = component_options[selected_component]

        st.markdown("### Define Attributes")

        attribute_values = {}

        for attribute in attributes:
            st.markdown(f"#### {attribute}")

            col1, col2, col3 = st.columns([1, 2, 1])

            with col1:
                rule_type = st.selectbox(
                    f"{attribute} Type",
                    ["Manual", "Fixed", "Formula"],
                    key=f"{selected_product_code}_{selected_component_name}_{attribute}_type"
                )

            fixed_value = None
            formula_used = None
            quantity = None

            with col2:
                if rule_type == "Fixed":
                    fixed_value = st.number_input(
                        f"{attribute} Fixed Value",
                        value=0.0,
                        step=1.0,
                        key=f"{selected_product_code}_{selected_component_name}_{attribute}_fixed"
                    )

                elif rule_type == "Formula":
                    formula_used = st.text_input(
                        f"{attribute} Formula",
                        placeholder="Example: opening_width - 40",
                        key=f"{selected_product_code}_{selected_component_name}_{attribute}_formula"
                    )

                else:
                    st.info(f"{attribute} will be entered manually.")

            with col3:
                if attribute == "Quantity":
                    quantity = st.number_input(
                        "Qty",
                        min_value=1,
                        value=1,
                        step=1,
                        key=f"{selected_product_code}_{selected_component_name}_{attribute}_qty"
                    )

            attribute_values[attribute] = {
                "type": rule_type,
                "formula_used": formula_used,
                "fixed_value": fixed_value,
                "quantity": quantity
            }

        if st.button("Save Product Definition"):
            for attribute, values in attribute_values.items():
                if values["type"] == "Formula" and not values["formula_used"]:
                    st.warning(f"Please enter formula for {attribute}.")
                    st.stop()

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
                    selected_component_name
                )
            )

            display_order = 1

            for attribute, values in attribute_values.items():
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
                        selected_component_name,
                        attribute,
                        values["type"],
                        values["formula_used"],
                        values["quantity"],
                        values["fixed_value"],
                        display_order
                    )
                )

                display_order += 1

            conn.commit()
            st.success("Product definition saved successfully.")
            st.rerun()

    # =====================================================
    # 4. EXISTING PRODUCT DEFINITIONS
    # =====================================================
    with st.expander("4. Existing Product Definitions", expanded=True):
        st.subheader("Existing Product Definitions")

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

            selected_product = st.selectbox(
                "Select Product to View",
                list(product_options.keys()),
                key="view_product_rules"
            )

            selected_product_cat = product_options[selected_product]["product_cat"]
            selected_product_code = product_options[selected_product]["product_code"]

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
                ORDER BY component, display_order, attribute
                """,
                (
                    selected_product_cat,
                    selected_product_code
                )
            )

            st.dataframe(rules_df, use_container_width=True, hide_index=True)
