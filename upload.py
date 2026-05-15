import streamlit as st
import pandas as pd
import re
import math


# =========================================================
# EXTRACT VARIABLES FROM FORMULA
# =========================================================
def extract_formula_variables(formula):

    if not formula:
        return []

    ignore_words = {
        "abs",
        "max",
        "min",
        "round",
        "math"
    }

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        str(formula)
    )

    return sorted(
        list(
            set(
                v for v in variables
                if v not in ignore_words
            )
        )
    )


# =========================================================
# SAFE FORMULA EVALUATOR
# =========================================================
def evaluate_formula(formula, variables):

    allowed_names = {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
        "math": math
    }

    allowed_names.update(variables)

    return eval(
        formula,
        {"__builtins__": {}},
        allowed_names
    )


# =========================================================
# GET REQUIRED USER INPUTS
# =========================================================
def get_required_inputs(rules_df):

    all_formula_variables = set()

    for formula in rules_df["formula_used"].dropna():

        vars_found = extract_formula_variables(formula)

        for var in vars_found:
            all_formula_variables.add(var)

    calculated_attributes = set(
        rules_df["attribute"]
        .dropna()
        .astype(str)
        .tolist()
    )

    required_inputs = sorted(
        list(
            all_formula_variables
            - calculated_attributes
        )
    )

    return required_inputs


# =========================================================
# RESOLVE FORMULAS RECURSIVELY
# =========================================================
def resolve_component_formulas(
    rules_df,
    user_inputs
):

    calculated = dict(user_inputs)

    results = []

    pending_rules = rules_df.to_dict("records")

    max_iterations = 100

    iteration = 0

    while pending_rules and iteration < max_iterations:

        iteration += 1

        unresolved = []

        progress_made = False

        for rule in pending_rules:

            component = str(rule["component"]).strip()

            attribute = str(rule["attribute"]).strip()

            rule_type = str(rule["type"]).lower().strip()

            formula = rule.get("formula_used")

            quantity = rule.get("quantity")

            try:

                # =====================================
                # FIXED
                # =====================================
                if rule_type == "fixed":

                    value = float(quantity)

                # =====================================
                # MANUAL
                # =====================================
                elif rule_type == "manual":

                    if attribute not in calculated:
                        unresolved.append(rule)
                        continue

                    value = calculated[attribute]

                # =====================================
                # FORMULA
                # =====================================
                elif rule_type == "formula":

                    required_vars = extract_formula_variables(
                        formula
                    )

                    missing_vars = [
                        var
                        for var in required_vars
                        if var not in calculated
                    ]

                    if missing_vars:
                        unresolved.append(rule)
                        continue

                    value = evaluate_formula(
                        formula,
                        calculated
                    )

                else:
                    unresolved.append(rule)
                    continue

                # =====================================
                # SAVE RESULT
                # =====================================
                result_key = f"{component}_{attribute}"

                calculated[result_key] = value

                # VERY IMPORTANT
                calculated[attribute] = value

                results.append({
                    "Component": component,
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Formula": formula,
                    "Value": value
                })

                progress_made = True

            except Exception as e:

                unresolved.append(rule)

        if not progress_made:
            break

        pending_rules = unresolved

    return results, pending_rules, calculated


# =========================================================
# MAIN COMPONENT CALCULATOR PAGE
# =========================================================
def show_component_calculator(conn):

    st.title("Component Calculator")

    # =====================================================
    # LOAD RULES
    # =====================================================
    query = """
        SELECT
            product_cat,
            product_code,
            component,
            attribute,
            type,
            formula_used,
            quantity
        FROM product_component_rules
    """

    rules_df = pd.read_sql(query, conn)

    if rules_df.empty:
        st.warning("No component rules found.")
        return

    # =====================================================
    # PROJECT SELECTION
    # =====================================================
    projects = pd.read_sql(
        "SELECT DISTINCT project_name FROM projects",
        conn
    )["project_name"].tolist()

    selected_project = st.selectbox(
        "Project",
        projects
    )

    # =====================================================
    # UNIT TYPES
    # =====================================================
    units = pd.read_sql(
        f"""
        SELECT DISTINCT unit_type
        FROM unit_types
        WHERE project_name = '{selected_project}'
        """,
        conn
    )["unit_type"].tolist()

    selected_unit = st.selectbox(
        "Unit Type",
        units
    )

    # =====================================================
    # HOUSES
    # =====================================================
    houses = pd.read_sql(
        f"""
        SELECT DISTINCT house_number
        FROM houses
        WHERE project_name = '{selected_project}'
        AND unit_type = '{selected_unit}'
        """,
        conn
    )["house_number"].tolist()

    selected_house = st.selectbox(
        "House Number",
        houses
    )

    # =====================================================
    # PRODUCTS
    # =====================================================
    products = pd.read_sql(
        """
        SELECT DISTINCT product_code
        FROM products
        """,
        conn
    )["product_code"].tolist()

    selected_product = st.selectbox(
        "Product",
        products
    )

    # =====================================================
    # FILTER PRODUCT RULES
    # =====================================================
    filtered_rules = rules_df[
        rules_df["product_code"] == selected_product
    ].copy()

    if filtered_rules.empty:
        st.error("No rules found.")
        return

    # =====================================================
    # GET REQUIRED INPUTS
    # =====================================================
    required_inputs = get_required_inputs(
        filtered_rules
    )

    st.subheader("Formula Inputs")

    user_inputs = {}

    cols = st.columns(4)

    for idx, variable in enumerate(required_inputs):

        with cols[idx % 4]:

            user_inputs[variable] = st.number_input(
                variable,
                value=0.0,
                step=1.0,
                key=variable
            )

    # =====================================================
    # CALCULATE BUTTON
    # =====================================================
    if st.button(
        "Generate Components",
        type="primary"
    ):

        results, pending, calculated = resolve_component_formulas(
            filtered_rules,
            user_inputs
        )

        # =================================================
        # RESULTS
        # =================================================
        st.subheader("Generated Components")

        if results:

            result_df = pd.DataFrame(results)

            st.dataframe(
                result_df,
                use_container_width=True,
                hide_index=True
            )

        else:
            st.warning("No components generated.")

        # =================================================
        # MISSING VARIABLES
        # =================================================
        if pending:

            st.subheader("Unresolved Rules")

            for rule in pending:

                formula = rule.get("formula_used")

                missing = []

                if formula:

                    required = extract_formula_variables(
                        formula
                    )

                    missing = [
                        var
                        for var in required
                        if var not in calculated
                    ]

                st.error(
                    f"{rule['component']} / "
                    f"{rule['attribute']} → "
                    f"Missing variables: "
                    f"{', '.join(missing)}"
                )

        # =================================================
        # DEBUG VARIABLES
        # =================================================
        st.subheader("Calculated Variables")

        st.json(calculated)
