def show_upload(conn, cur):
    import re
    import time
    import pandas as pd
    import streamlit as st
    from psycopg2.extras import execute_values

    if st.session_state.get("role") != "admin":
        st.error("Access denied")
        st.stop()

    st.title("📤 Upload Component Master Data")

    # =========================================================
    # HELPERS
    # =========================================================

    def clean_text(value):
        if pd.isna(value):
            return ""
        return str(value).strip()

    def clean_int(value):
        if pd.isna(value) or value == "":
            return None
        try:
            return int(float(value))
        except Exception:
            return None

    def normalize_columns(df):
        df.columns = (
            df.columns
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
            .str.replace("-", "_", regex=False)
        )
        return df

    def normalize_rule_type(value):
        value = clean_text(value).lower()

        if value in ["fomula", "formula", "formulas"]:
            return "formula"
        if value in ["fixed", "constant", "qty"]:
            return "fixed"
        if value in ["manual", "input", "user_input"]:
            return "manual"

        return value

    def split_product_codes(value):
        value = clean_text(value)
        if not value:
            return []

        return [
            code.strip()
            for code in value.split(",")
            if code.strip()
        ]

    def normalize_formula(formula):
        formula = clean_text(formula)

        if not formula:
            return ""

        if "=" in formula:
            left, right = formula.split("=", 1)
            if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*", left):
                formula = right.strip()

        return formula

    def extract_formula_variables(formula):
        formula = normalize_formula(formula)

        if not formula:
            return []

        ignore_words = {
            "abs",
            "max",
            "min",
            "round",
            "float",
            "int",
            "decimal",
            "Decimal"
        }

        variables = re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            formula
        )

        return sorted({
            v.strip()
            for v in variables
            if v.strip() not in ignore_words
        })

    def insert_values_where_not_exists(
        table,
        columns,
        rows,
        conflict_columns
    ):
        if not rows:
            return 0

        column_sql = ", ".join(columns)
        value_alias = ", ".join(columns)

        conflict_sql = " AND ".join([
            f"COALESCE(t.{col}::TEXT, '') = COALESCE(v.{col}::TEXT, '')"
            for col in conflict_columns
        ])

        query = f"""
            INSERT INTO {table}
            ({column_sql})
            SELECT {column_sql}
            FROM (VALUES %s) AS v({value_alias})
            WHERE NOT EXISTS (
                SELECT 1
                FROM {table} t
                WHERE {conflict_sql}
            )
        """

        execute_values(cur, query, rows)
        return cur.rowcount

    # =========================================================
    # READ COMPONENT ARCHITECTURE
    # =========================================================

    def read_component_architecture(file):
        raw_df = pd.read_excel(
            file,
            sheet_name=0,
            header=None,
            engine="openpyxl"
        )

        header_row_index = None

        for index, row in raw_df.iterrows():
            row_values = [
                str(value).strip().lower()
                for value in row.tolist()
                if not pd.isna(value)
            ]

            if (
                "product_cat" in row_values
                and "product_code" in row_values
            ):
                header_row_index = index
                break

        if header_row_index is None:
            raise Exception(
                "Could not find Product_Cat and Product_Code header row"
            )

        df = pd.read_excel(
            file,
            sheet_name=0,
            header=header_row_index,
            engine="openpyxl"
        )

        df = normalize_columns(df)

        df = df.rename(columns={
            "components": "component",
            "component": "component",
            "formula": "formula_used",
            "formula_used": "formula_used",
            "quanity": "quantity",
            "quantity": "quantity"
        })

        required_cols = [
            "product_cat",
            "product_code",
            "component",
            "attribute",
            "type",
            "formula_used",
            "quantity"
        ]

        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing column: {col}")
                st.stop()

        df = df[required_cols]

        df["product_cat"] = df["product_cat"].ffill()
        df["product_code"] = df["product_code"].ffill()
        df["component"] = df["component"].ffill()

        df = df.dropna(
            subset=[
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type"
            ]
        )

        df["product_cat"] = df["product_cat"].apply(clean_text)
        df["product_code"] = df["product_code"].apply(clean_text)
        df["component"] = df["component"].apply(clean_text)
        df["attribute"] = df["attribute"].apply(clean_text)
        df["type"] = df["type"].apply(normalize_rule_type)
        df["formula_used"] = df["formula_used"].apply(normalize_formula)
        df["quantity"] = df["quantity"].apply(clean_int)

        df["quantity"] = (
            df.groupby(
                [
                    "product_cat",
                    "product_code",
                    "component"
                ]
            )["quantity"]
            .ffill()
        )

        df.loc[
            df["component"].str.lower().str.strip() == "flush shutter",
            "quantity"
        ] = 1

        expanded_rows = []

        for _, row in df.iterrows():
            for product_code in split_product_codes(row["product_code"]):
                expanded_rows.append({
                    "product_cat": row["product_cat"],
                    "product_code": product_code,
                    "component": row["component"],
                    "attribute": row["attribute"],
                    "type": row["type"],
                    "formula_used": row["formula_used"],
                    "quantity": clean_int(row["quantity"]),
                })

        df = pd.DataFrame(expanded_rows)

        if df.empty:
            raise Exception("No valid component rules found")

        df = df.drop_duplicates(
            subset=[
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type",
                "formula_used",
                "quantity"
            ]
        )

        return df

    # =========================================================
    # READ PROJECT MASTER
    # =========================================================

    def read_project_master(file):
        df = pd.read_excel(
            file,
            sheet_name=0,
            engine="openpyxl"
        )

        df = normalize_columns(df)

        df = df.rename(columns={
            "unit_name": "unit_type",
            "house_no": "house_number",
            "product_category": "product_cat"
        })

        required_cols = [
            "project_name",
            "unit_type",
            "house_number",
            "product_cat",
            "product_code",
            "orientation",
            "quantity"
        ]

        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing column: {col}")
                st.stop()

        df = df[required_cols]

        df = df.dropna(
            subset=[
                "project_name",
                "unit_type",
                "house_number"
            ]
        )

        df["project_name"] = df["project_name"].apply(clean_text)
        df["unit_type"] = df["unit_type"].apply(clean_text)
        df["house_number"] = df["house_number"].apply(clean_text)
        df["product_cat"] = df["product_cat"].apply(clean_text)
        df["product_code"] = df["product_code"].apply(clean_text)
        df["orientation"] = df["orientation"].apply(clean_text)

        df["quantity"] = (
            pd.to_numeric(df["quantity"], errors="coerce")
            .fillna(1)
            .astype(int)
        )

        df = df.drop_duplicates()

        return df

    # =========================================================
    # UPLOAD COMPONENT ARCHITECTURE
    # =========================================================

    def upload_component_architecture(df):
        start_time = time.time()

        status = st.empty()
        progress = st.progress(0)
        eta_box = st.empty()

        status.info("⏳ Uploading... Please wait")

        total_rows = len(df)

        product_rows = (
            df[["product_cat", "product_code"]]
            .drop_duplicates()
            .values
            .tolist()
        )

        inserted_products = insert_values_where_not_exists(
            "products",
            ["product_cat", "product_code"],
            product_rows,
            ["product_cat", "product_code"]
        )

        conn.commit()
        progress.progress(20)

        rule_rows = (
            df[
                [
                    "product_cat",
                    "product_code",
                    "component",
                    "attribute",
                    "type",
                    "formula_used",
                    "quantity"
                ]
            ]
            .drop_duplicates()
            .values
            .tolist()
        )

        inserted_rules = insert_values_where_not_exists(
            "product_component_rules",
            [
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type",
                "formula_used",
                "quantity"
            ],
            rule_rows,
            [
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type",
                "formula_used",
                "quantity"
            ]
        )

        conn.commit()
        progress.progress(55)

        variable_set = set()

        for formula in df["formula_used"].dropna():
            for variable in extract_formula_variables(formula):
                variable_set.add(variable)

        variable_rows = [
            (
                variable,
                "Auto-created from uploaded formula rule"
            )
            for variable in sorted(variable_set)
        ]

        inserted_variables = insert_values_where_not_exists(
            "formula_variables",
            ["variable_name", "description"],
            variable_rows,
            ["variable_name"]
        )

        conn.commit()
        progress.progress(75)

        input_rows = (
            df[["component", "attribute", "type"]]
            .drop_duplicates()
            .values
            .tolist()
        )

        inserted_inputs = insert_values_where_not_exists(
            "component_inputs",
            ["component", "input_name", "input_type"],
            input_rows,
            ["component", "input_name", "input_type"]
        )

        conn.commit()
        progress.progress(100)

        total_time = round(time.time() - start_time, 2)
        status.empty()

        st.success(f"""
🚀 Upload Completed Successfully

⏱ Time: {total_time} sec
📄 Excel Rows: {total_rows}

📊 Summary:
- Product Types: {len(product_rows)}
- Newly Added Products: {inserted_products}
- Component Rules Added: {inserted_rules}
- Formula Variables Added: {inserted_variables}
- Component Inputs Added: {inserted_inputs}
""")

        eta_box.info(f"""
⚡ Speed:
{round(total_rows / total_time, 2) if total_time > 0 else total_rows}
rows/sec
""")

    # =========================================================
    # UPLOAD PROJECT MASTER
    # =========================================================

    def upload_project_master(df):
        start_time = time.time()

        status = st.empty()
        progress = st.progress(0)
        eta_box = st.empty()

        status.info("⏳ Uploading... Please wait")

        total_rows = len(df)

        project_rows = [
            (p,)
            for p in sorted(set(df["project_name"]))
            if p
        ]

        inserted_projects = insert_values_where_not_exists(
            "projects",
            ["project_name"],
            project_rows,
            ["project_name"]
        )

        conn.commit()
        progress.progress(25)

        unit_rows = (
            df[["project_name", "unit_type"]]
            .drop_duplicates()
            .values
            .tolist()
        )

        inserted_units = insert_values_where_not_exists(
            "unit_types",
            ["project_name", "unit_type"],
            unit_rows,
            ["project_name", "unit_type"]
        )

        conn.commit()
        progress.progress(50)

        house_rows = (
            df[["project_name", "unit_type", "house_number"]]
            .drop_duplicates()
            .values
            .tolist()
        )

        inserted_houses = insert_values_where_not_exists(
            "houses",
            ["project_name", "unit_type", "house_number"],
            house_rows,
            ["project_name", "unit_type", "house_number"]
        )

        conn.commit()
        progress.progress(75)

        product_rows = (
            df[["product_cat", "product_code"]]
            .drop_duplicates()
        )

        product_rows = product_rows[
            (product_rows["product_cat"] != "")
            & (product_rows["product_code"] != "")
        ].values.tolist()

        inserted_products = insert_values_where_not_exists(
            "products",
            ["product_cat", "product_code"],
            product_rows,
            ["product_cat", "product_code"]
        )

        conn.commit()
        progress.progress(100)

        total_time = round(time.time() - start_time, 2)
        status.empty()

        st.success(f"""
🚀 Upload Completed Successfully

⏱ Time: {total_time} sec
📄 Excel Rows: {total_rows}

📊 Summary:
- Projects Added: {inserted_projects}
- Unit Types Added: {inserted_units}
- Houses Added: {inserted_houses}
- Products Added: {inserted_products}
""")

        eta_box.info(f"""
⚡ Speed:
{round(total_rows / total_time, 2) if total_time > 0 else total_rows}
rows/sec
""")

    # =========================================================
    # UPLOAD UI
    # =========================================================

    upload_type = st.selectbox(
        "Select Upload Type",
        [
            "Component Architecture",
            "Project Master"
        ]
    )

    file = st.file_uploader(
        "Upload Excel",
        type=["xlsx", "xls"]
    )

    if file:
        try:
            if upload_type == "Component Architecture":
                df = read_component_architecture(file)
            else:
                df = read_project_master(file)

        except Exception as e:
            st.error(f"❌ Excel read failed: {e}")
            st.stop()

        total_rows = len(df)

        st.info(f"📊 Estimated Rows: {total_rows}")

        if st.button("Upload to Master Database", type="primary"):
            try:
                if upload_type == "Component Architecture":
                    upload_component_architecture(df)
                else:
                    upload_project_master(df)

            except Exception as e:
                conn.rollback()
                st.error(f"❌ Upload failed: {e}")

    st.divider()

    # =========================================================
    # ADD EXTRA PRODUCT
    # =========================================================

    st.subheader("➕ Add Extra Product")

    row1_col1, row1_col2 = st.columns(2)

    with row1_col1:
        quick_product_cat = st.text_input(
            "Product Category",
            key="quick_product_cat"
        )

    with row1_col2:
        quick_product_code = st.text_input(
            "Product Code",
            key="quick_product_code"
        )

    add_product_btn = st.button("➕ Add Product Instantly")

    if add_product_btn:
        product_cat = quick_product_cat.strip()
        product_code = quick_product_code.strip()

        if not product_cat or not product_code:
            st.warning("Product category and product code required")
            st.stop()

        try:
            cur.execute("""
                INSERT INTO products
                (
                    product_cat,
                    product_code
                )
                SELECT %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM products
                    WHERE product_cat = %s
                    AND product_code = %s
                )
            """, (
                product_cat,
                product_code,
                product_cat,
                product_code
            ))

            inserted = cur.rowcount
            conn.commit()

            st.success(f"""
✅ Product Added Successfully

Product Category:
{product_cat}

Product Code:
{product_code}

Inserted:
{inserted}

Existing Preserved:
{0 if inserted else 1}
""")

        except Exception as e:
            conn.rollback()
            st.error(f"Add product failed: {e}")

    st.divider()

    # =========================================================
    # RENAME PRODUCT CODE
    # =========================================================

    st.subheader("✏ Rename / Correct Product Code")

    cur.execute("""
        SELECT DISTINCT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
    """)

    products = cur.fetchall()

    if products:
        product_map = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in products
        }

        rename_col1, rename_col2 = st.columns(2)

        with rename_col1:
            old_products = st.multiselect(
                "Select Product Codes",
                options=list(product_map.keys()),
                key="rename_old_products"
            )

        with rename_col2:
            new_code = st.text_input(
                "Enter New Product Code",
                key="rename_new_code"
            )

        rename_btn = st.button("✅ Update Product Code")

        if rename_btn:
            if not old_products:
                st.warning("Please select product codes")
            elif not new_code.strip():
                st.warning("Please enter new product code")
            else:
                try:
                    updated_products = 0
                    updated_rules = 0

                    for label in old_products:
                        old_cat, old_code = product_map[label]

                        cur.execute("""
                            UPDATE products
                            SET product_code = %s
                            WHERE product_cat = %s
                            AND product_code = %s
                        """, (
                            new_code.strip(),
                            old_cat,
                            old_code
                        ))

                        updated_products += cur.rowcount

                        cur.execute("""
                            UPDATE product_component_rules
                            SET product_code = %s
                            WHERE product_cat = %s
                            AND product_code = %s
                        """, (
                            new_code.strip(),
                            old_cat,
                            old_code
                        ))

                        updated_rules += cur.rowcount

                    conn.commit()

                    st.success(f"""
✅ Product Code Updated Successfully

New Product Code:
{new_code.strip()}

Updated Products:
{updated_products}

Updated Formula Rules:
{updated_rules}
""")

                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Rename failed: {e}")

    st.divider()

    # =========================================================
    # ADD FORMULA
    # =========================================================

    st.subheader("➕ Add Formula / Component Rule")

    cur.execute("""
        SELECT DISTINCT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
    """)

    add_products = cur.fetchall()

    if add_products:
        add_product_map = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in add_products
        }

        add_row1_col1, add_row1_col2 = st.columns(2)

        with add_row1_col1:
            add_product_label = st.selectbox(
                "Product",
                list(add_product_map.keys()),
                key="add_formula_product"
            )

        with add_row1_col2:
            add_rule_type = st.selectbox(
                "Type",
                ["formula", "fixed", "manual"],
                key="add_formula_type"
            )

        add_row2_col1, add_row2_col2, add_row2_col3 = st.columns(3)

        with add_row2_col1:
            add_component = st.text_input(
                "Component",
                key="add_component"
            )

        with add_row2_col2:
            add_attribute = st.text_input(
                "Attribute",
                key="add_attribute"
            )

        with add_row2_col3:
            add_quantity = st.number_input(
                "Quantity",
                min_value=0,
                value=1,
                step=1,
                key="add_quantity"
            )

        add_formula_used = st.text_input(
            "Formula Used",
            key="add_formula_used"
        )

        add_formula_btn = st.button("➕ Add Formula Rule")

        if add_formula_btn:
            product_cat, product_code = add_product_map[
                add_product_label
            ]

            if not add_component.strip() or not add_attribute.strip():
                st.warning("Component and attribute required")
            else:
                try:
                    formula_value = normalize_formula(
                        add_formula_used
                    )

                    cur.execute("""
                        INSERT INTO product_component_rules
                        (
                            product_cat,
                            product_code,
                            component,
                            attribute,
                            type,
                            formula_used,
                            quantity
                        )
                        SELECT %s, %s, %s, %s, %s, %s, %s
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM product_component_rules
                            WHERE product_cat = %s
                            AND product_code = %s
                            AND component = %s
                            AND attribute = %s
                            AND type = %s
                            AND COALESCE(formula_used, '') = COALESCE(%s, '')
                            AND COALESCE(quantity, -1) = COALESCE(%s, -1)
                        )
                    """, (
                        product_cat,
                        product_code,
                        add_component.strip(),
                        add_attribute.strip(),
                        add_rule_type,
                        formula_value,
                        int(add_quantity),
                        product_cat,
                        product_code,
                        add_component.strip(),
                        add_attribute.strip(),
                        add_rule_type,
                        formula_value,
                        int(add_quantity)
                    ))

                    inserted_rule = cur.rowcount

                    for variable in extract_formula_variables(
                        formula_value
                    ):
                        cur.execute("""
                            INSERT INTO formula_variables
                            (
                                variable_name,
                                description
                            )
                            VALUES (%s, %s)
                            ON CONFLICT (variable_name) DO NOTHING
                        """, (
                            variable,
                            "Auto-created from manually added formula rule"
                        ))

                    cur.execute("""
                        INSERT INTO component_inputs
                        (
                            component,
                            input_name,
                            input_type
                        )
                        SELECT %s, %s, %s
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM component_inputs
                            WHERE component = %s
                            AND input_name = %s
                            AND input_type = %s
                        )
                    """, (
                        add_component.strip(),
                        add_attribute.strip(),
                        add_rule_type,
                        add_component.strip(),
                        add_attribute.strip(),
                        add_rule_type
                    ))

                    conn.commit()

                    st.success(f"""
✅ Formula Rule Added

Product:
{product_cat} | {product_code}

Inserted:
{inserted_rule}

Existing Preserved:
{0 if inserted_rule else 1}
""")

                except Exception as e:
                    conn.rollback()
                    st.error(f"Add formula failed: {e}")

    st.divider()

    # =========================================================
    # EDIT FORMULA
    # =========================================================

    st.subheader("✏ Edit Formula / Component Rule")

    cur.execute("""
        SELECT DISTINCT product_cat, product_code
        FROM product_component_rules
        ORDER BY product_cat, product_code
    """)

    formula_products = cur.fetchall()

    if formula_products:
        edit_product_map = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in formula_products
        }

        edit_product_label = st.selectbox(
            "Select Product",
            list(edit_product_map.keys()),
            key="edit_formula_product"
        )

        edit_product_cat, edit_product_code = edit_product_map[
            edit_product_label
        ]

        cur.execute("""
            SELECT
                product_cat,
                product_code,
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
            edit_product_cat,
            edit_product_code
        ))

        rules = cur.fetchall()

        if rules:
            rule_map = {}

            for index, rule in enumerate(rules):
                label = (
                    f"{rule[2]} | {rule[3]} | {rule[4]} | "
                    f"{rule[5] or ''} | Qty: {rule[6]}"
                )

                rule_map[label] = index

            selected_rule_label = st.selectbox(
                "Select Formula Rule",
                list(rule_map.keys()),
                key="edit_formula_rule"
            )

            selected_rule = rules[
                rule_map[selected_rule_label]
            ]

            edit_col1, edit_col2, edit_col3 = st.columns(3)

            with edit_col1:
                edit_component = st.text_input(
                    "Component",
                    value=selected_rule[2],
                    key="edit_component"
                )

            with edit_col2:
                edit_attribute = st.text_input(
                    "Attribute",
                    value=selected_rule[3],
                    key="edit_attribute"
                )

            with edit_col3:
                normalized_type = normalize_rule_type(
                    selected_rule[4]
                )

                if normalized_type not in [
                    "formula",
                    "fixed",
                    "manual"
                ]:
                    normalized_type = "formula"

                edit_type = st.selectbox(
                    "Type",
                    ["formula", "fixed", "manual"],
                    index=[
                        "formula",
                        "fixed",
                        "manual"
                    ].index(normalized_type),
                    key="edit_type"
                )

            edit_formula = st.text_input(
                "Formula Used",
                value=selected_rule[5] or "",
                key="edit_formula"
            )

            edit_quantity = st.number_input(
                "Quantity",
                min_value=0,
                value=int(selected_rule[6] or 0),
                step=1,
                key="edit_quantity"
            )

            update_formula_btn = st.button(
                "✅ Update Formula Rule"
            )

            if update_formula_btn:
                try:
                    new_formula = normalize_formula(
                        edit_formula
                    )

                    cur.execute("""
                        UPDATE product_component_rules
                        SET
                            component = %s,
                            attribute = %s,
                            type = %s,
                            formula_used = %s,
                            quantity = %s
                        WHERE product_cat = %s
                        AND product_code = %s
                        AND component = %s
                        AND attribute = %s
                        AND type = %s
                        AND COALESCE(formula_used, '') = COALESCE(%s, '')
                        AND COALESCE(quantity, -1) = COALESCE(%s, -1)
                    """, (
                        edit_component.strip(),
                        edit_attribute.strip(),
                        edit_type,
                        new_formula,
                        int(edit_quantity),
                        selected_rule[0],
                        selected_rule[1],
                        selected_rule[2],
                        selected_rule[3],
                        selected_rule[4],
                        selected_rule[5],
                        selected_rule[6]
                    ))

                    updated_rules = cur.rowcount

                    for variable in extract_formula_variables(
                        new_formula
                    ):
                        cur.execute("""
                            INSERT INTO formula_variables
                            (
                                variable_name,
                                description
                            )
                            VALUES (%s, %s)
                            ON CONFLICT (variable_name) DO NOTHING
                        """, (
                            variable,
                            "Auto-created from edited formula rule"
                        ))

                    conn.commit()

                    st.success(f"""
✅ Formula Rule Updated Successfully

Updated Rows:
{updated_rules}
""")

                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Edit formula failed: {e}")
