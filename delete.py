def show_delete(conn, cur):
    import streamlit as st

    if st.session_state.get("role") != "admin":
        st.error("Access denied")
        st.stop()

    st.title("Delete Master Data")

    # =========================================================
    # HELPERS
    # =========================================================

    def safe_execute(query, params=None):
        try:
            cur.execute(query, params or ())
        except Exception as e:
            conn.rollback()
            raise e

    def fetch_all(query, params=None):
        safe_execute(query, params)
        return cur.fetchall()

    def delete_component_rules_for_product(product_cat, product_code):
        safe_execute("""
            DELETE FROM product_component_rules
            WHERE product_cat = %s
            AND product_code = %s
        """, (product_cat, product_code))

    def delete_product_if_unused(product_cat, product_code):
        safe_execute("""
            DELETE FROM products
            WHERE product_cat = %s
            AND product_code = %s
            AND NOT EXISTS (
                SELECT 1
                FROM product_component_rules
                WHERE product_cat = %s
                AND product_code = %s
            )
        """, (
            product_cat,
            product_code,
            product_cat,
            product_code
        ))

    # =========================================================
    # DELETE TYPE
    # =========================================================

    delete_type = st.radio(
        "Delete Level",
        [
            "Project",
            "Unit Type",
            "House",
            "Product",
            "Formula"
        ]
    )

    confirm = st.checkbox("I confirm this delete action")

    # =========================================================
    # PROJECT BASE
    # =========================================================

    projects = fetch_all("""
        SELECT project_name
        FROM projects
        ORDER BY project_name
    """)

    project_names = [p[0] for p in projects]

    if delete_type in ["Project", "Unit Type", "House"]:
        if not project_names:
            st.warning("No projects found")
            return

        selected_project = st.selectbox(
            "Project",
            project_names
        )

    # =========================================================
    # DELETE PROJECT
    # =========================================================

    if delete_type == "Project":

        st.warning(
            "This will delete the selected project, its unit types, and houses."
        )

        if st.button("Delete Project"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            try:
                safe_execute("""
                    DELETE FROM houses
                    WHERE project_name = %s
                """, (selected_project,))

                safe_execute("""
                    DELETE FROM unit_types
                    WHERE project_name = %s
                """, (selected_project,))

                safe_execute("""
                    DELETE FROM projects
                    WHERE project_name = %s
                """, (selected_project,))

                conn.commit()
                st.success("Project deleted successfully")
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Project delete failed: {e}")

    # =========================================================
    # DELETE UNIT TYPE
    # =========================================================

    elif delete_type == "Unit Type":

        units = fetch_all("""
            SELECT unit_type
            FROM unit_types
            WHERE project_name = %s
            ORDER BY unit_type
        """, (selected_project,))

        unit_types = [u[0] for u in units]

        if not unit_types:
            st.warning("No unit types found")
            return

        selected_unit = st.selectbox(
            "Unit Type",
            unit_types
        )

        st.warning(
            "This will delete the selected unit type and its houses."
        )

        if st.button("Delete Unit Type"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            try:
                safe_execute("""
                    DELETE FROM houses
                    WHERE project_name = %s
                    AND unit_type = %s
                """, (
                    selected_project,
                    selected_unit
                ))

                safe_execute("""
                    DELETE FROM unit_types
                    WHERE project_name = %s
                    AND unit_type = %s
                """, (
                    selected_project,
                    selected_unit
                ))

                conn.commit()
                st.success("Unit type deleted successfully")
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Unit type delete failed: {e}")

    # =========================================================
    # DELETE HOUSE
    # =========================================================

    elif delete_type == "House":

        units = fetch_all("""
            SELECT unit_type
            FROM unit_types
            WHERE project_name = %s
            ORDER BY unit_type
        """, (selected_project,))

        unit_types = [u[0] for u in units]

        if not unit_types:
            st.warning("No unit types found")
            return

        selected_unit = st.selectbox(
            "Unit Type",
            unit_types
        )

        houses = fetch_all("""
            SELECT house_number
            FROM houses
            WHERE project_name = %s
            AND unit_type = %s
            ORDER BY house_number
        """, (
            selected_project,
            selected_unit
        ))

        house_numbers = [h[0] for h in houses]

        if not house_numbers:
            st.warning("No houses found")
            return

        selected_houses = st.multiselect(
            "House Number",
            house_numbers
        )

        if st.button("Delete Selected Houses"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_houses:
                st.warning("Please select houses")
                return

            try:
                safe_execute("""
                    DELETE FROM houses
                    WHERE project_name = %s
                    AND unit_type = %s
                    AND house_number = ANY(%s)
                """, (
                    selected_project,
                    selected_unit,
                    selected_houses
                ))

                conn.commit()
                st.success(
                    f"{len(selected_houses)} house(s) deleted successfully"
                )
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"House delete failed: {e}")

    # =========================================================
    # DELETE PRODUCT
    # =========================================================

    elif delete_type == "Product":

        products = fetch_all("""
            SELECT DISTINCT product_cat, product_code
            FROM products
            ORDER BY product_cat, product_code
        """)

        if not products:
            st.warning("No products found")
            return

        product_dict = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in products
        }

        selected_products = st.multiselect(
            "Products",
            list(product_dict.keys())
        )

        delete_rules_too = st.checkbox(
            "Also delete this product's component rules",
            value=True
        )

        st.warning(
            "Deleting product rules will remove formulas and component setup for the selected product."
        )

        if st.button("Delete Selected Products"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_products:
                st.warning("Please select products")
                return

            try:
                deleted_count = 0

                for product_label in selected_products:
                    product_cat, product_code = product_dict[product_label]

                    if delete_rules_too:
                        delete_component_rules_for_product(
                            product_cat,
                            product_code
                        )

                    safe_execute("""
                        DELETE FROM products
                        WHERE product_cat = %s
                        AND product_code = %s
                    """, (
                        product_cat,
                        product_code
                    ))

                    deleted_count += 1

                conn.commit()

                st.success(
                    f"{deleted_count} product(s) deleted successfully"
                )
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Product delete failed: {e}")

    # =========================================================
    # DELETE FORMULA / COMPONENT RULE
    # =========================================================

    elif delete_type == "Formula":

        products = fetch_all("""
            SELECT DISTINCT product_cat, product_code
            FROM product_component_rules
            ORDER BY product_cat, product_code
        """)

        if not products:
            st.warning("No formula rules found")
            return

        product_dict = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in products
        }

        selected_product = st.selectbox(
            "Product",
            list(product_dict.keys())
        )

        product_cat, product_code = product_dict[selected_product]

        rules = fetch_all("""
            SELECT
                component,
                attribute,
                type,
                formula_used,
                quantity
            FROM product_component_rules
            WHERE product_cat = %s
            AND product_code = %s
            ORDER BY component, attribute
        """, (
            product_cat,
            product_code
        ))

        if not rules:
            st.warning("No rules found for selected product")
            return

        rule_dict = {}

        for index, rule in enumerate(rules):
            component = rule[0]
            attribute = rule[1]
            rule_type = rule[2]
            formula_used = rule[3]
            quantity = rule[4]

            label = (
                f"{component} | {attribute} | {rule_type} | "
                f"{formula_used or ''} | Qty: {quantity}"
            )

            rule_dict[label] = index

        selected_rules = st.multiselect(
            "Formula / Component Rules",
            list(rule_dict.keys())
        )

        delete_variable_master = st.checkbox(
            "Also delete unused formula variables from formula_variables",
            value=False
        )

        if st.button("Delete Selected Formula Rules"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_rules:
                st.warning("Please select formula rules")
                return

            try:
                deleted_count = 0

                for label in selected_rules:
                    rule = rules[rule_dict[label]]

                    safe_execute("""
                        DELETE FROM product_component_rules
                        WHERE product_cat = %s
                        AND product_code = %s
                        AND component = %s
                        AND attribute = %s
                        AND type = %s
                        AND COALESCE(formula_used, '') = COALESCE(%s, '')
                        AND COALESCE(quantity, -1) = COALESCE(%s, -1)
                    """, (
                        product_cat,
                        product_code,
                        rule[0],
                        rule[1],
                        rule[2],
                        rule[3],
                        rule[4]
                    ))

                    deleted_count += cur.rowcount

                if delete_variable_master:
                    safe_execute("""
                        DELETE FROM formula_variables fv
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM product_component_rules pcr
                            WHERE COALESCE(pcr.formula_used, '') LIKE
                                  '%' || fv.variable_name || '%'
                        )
                    """)

                conn.commit()

                st.success(
                    f"{deleted_count} formula rule(s) deleted successfully"
                )
                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Formula delete failed: {e}")
