import re
import pandas as pd
import streamlit as st


# =========================================================
# SAFE FORMULA EVALUATION
# =========================================================
def safe_eval_formula(formula, context):
    """
    Safely evaluate formula using already available context values
    """

    allowed_names = {
        k: float(v)
        for k, v in context.items()
        if v is not None and str(v) != ""
    }

    return eval(
        formula,
        {"__builtins__": {}},
        allowed_names
    )


# =========================================================
# EXTRACT VARIABLES
# =========================================================
def extract_formula_variables(formula):

    ignore_words = {
        "abs",
        "max",
        "min",
        "round"
    }

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        str(formula)
    )

    return sorted(
        set(v for v in variables if v not in ignore_words)
    )


# =========================================================
# GET REQUIRED USER INPUTS
# =========================================================
def get_required_manual_inputs(rules_df):

    calculated_outputs = set()

    for _, row in rules_df.iterrows():

        component = str(row["component"]).strip()
        attribute = str(row["attribute"]).strip()

        output_name = f"{component}_{attribute}" \
            .lower() \
            .replace(" ", "_")

        calculated_outputs.add(output_name)

    all_formula_variables = set()

    for _, row in rules_df.iterrows():

        formula = row.get("formula_used")

        if pd.isna(formula):
            continue

        variables = extract_formula_variables(formula)

        for v in variables:
            all_formula_variables.add(v)

    # ONLY variables not produced by formulas
    manual_inputs = sorted(
        all_formula_variables - calculated_outputs
    )

    return manual_inputs


# =========================================================
# MAIN COMPONENT CALCULATION ENGINE
# =========================================================
def run_component_engine(rules_df, user_inputs):

    calculation_context = {}

    # =====================================================
    # LOAD USER INPUTS
    # =====================================================
    for key, value in user_inputs.items():

        calculation_context[key] = value

    generated_components = []

    errors = []

    # =====================================================
    # ITERATIVE SOLVER
    # Handles chained dependencies
    # =====================================================
    pending_rules = rules_df.copy()

    max_iterations = 50

    iteration = 0

    while not pending_rules.empty and iteration < max_iterations:

        solved_in_this_iteration = []

        for idx, row in pending_rules.iterrows():

            component = str(row["component"]).strip()

            attribute = str(row["attribute"]).strip()

            formula = row.get("formula_used")

            rule_type = str(row["type"]).lower().strip()

            quantity = row.get("quantity", 1)

            output_name = f"{component}_{attribute}" \
                .lower() \
                .replace(" ", "_")

            try:

                # =========================================
                # FIXED VALUE
                # =========================================
                if rule_type == "fixed":

                    result = quantity

                # =========================================
                # MANUAL VALUE
                # =========================================
                elif rule_type == "manual":

                    if attribute not in calculation_context:

                        raise Exception(
                            f"Missing manual input: {attribute}"
                        )

                    result = calculation_context[attribute]

                # =========================================
                # FORMULA VALUE
                # =========================================
                elif rule_type == "formula":

                    variables = extract_formula_variables(formula)

                    missing = [
                        v for v in variables
                        if v not in calculation_context
                    ]

                    # skip for next iteration
                    if missing:
                        continue

                    result = safe_eval_formula(
                        formula,
                        calculation_context
                    )

                else:
                    raise Exception(
                        f"Unknown rule type: {rule_type}"
                    )

                # =========================================
                # SAVE RESULT
                # =========================================
                calculation_context[output_name] = result

                generated_components.append({
                    "Component": component,
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Formula": formula,
                    "Value": result
                })

                solved_in_this_iteration.append(idx)

            except Exception as e:

                errors.append(
                    f"{component} / {attribute}: {str(e)}"
                )

        # remove solved
        pending_rules = pending_rules.drop(solved_in_this_iteration)

        # no progress means dependency deadlock
        if not solved_in_this_iteration:
            break

        iteration += 1

    # =====================================================
    # FINAL UNSOLVED RULES
    # =====================================================
    if not pending_rules.empty:

        for _, row in pending_rules.iterrows():

            component = row["component"]

            attribute = row["attribute"]

            formula = row.get("formula_used")

            variables = extract_formula_variables(formula)

            missing = [
                v for v in variables
                if v not in calculation_context
            ]

            errors.append(
                f"{component} / {attribute}: "
                f"Missing variables: {', '.join(missing)}"
            )

    return generated_components, errors, calculation_context


# =========================================================
# STREAMLIT UI
# =========================================================
def show_component_calculator(rules_df):

    st.title("Component Calculator")

    st.subheader("Formula Inputs")

    # =====================================================
    # AUTO DETECT ONLY TRUE MANUAL INPUTS
    # =====================================================
    required_inputs = get_required_manual_inputs(rules_df)

    user_inputs = {}

    cols = st.columns(4)

    for i, variable in enumerate(required_inputs):

        with cols[i % 4]:

            value = st.number_input(
                variable,
                value=0.0,
                step=1.0,
                key=variable
            )

            user_inputs[variable] = value

    st.divider()

    # =====================================================
    # RUN ENGINE
    # =====================================================
    generated_components, errors, context = run_component_engine(
        rules_df,
        user_inputs
    )

    st.subheader("Generated Component Preview")

    # =====================================================
    # SHOW ERRORS
    # =====================================================
    if errors:

        for err in errors:
            st.error(err)

    # =====================================================
    # SHOW GENERATED TABLE
    # =====================================================
    if generated_components:

        preview_df = pd.DataFrame(generated_components)

        st.dataframe(
            preview_df,
            use_container_width=True,
            hide_index=True
        )

    # =====================================================
    # DEBUG CONTEXT
    # =====================================================
    with st.expander("Calculation Context"):

        context_df = pd.DataFrame([
            {
                "Variable": k,
                "Value": v
            }
            for k, v in context.items()
        ])

        st.dataframe(
            context_df,
            use_container_width=True,
            hide_index=True
        )
