import streamlit as st
import psycopg2
from PIL import Image


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="OperaFlow Component App",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# SAFE EXECUTE
# =========================================================
def safe_execute(conn, cur, query, params=None):
    try:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
    except Exception as e:
        conn.rollback()
        raise e


# =========================================================
# IMAGE PROCESS
# =========================================================
def remove_white_bg(image_path):
    img = Image.open(image_path).convert("RGBA")
    datas = img.getdata()

    new_data = []

    for item in datas:
        if item[0] > 240 and item[1] > 240 and item[2] > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)

    img.putdata(new_data)

    return img


# =========================================================
# SESSION DEFAULTS
# =========================================================
defaults = {
    "logged_in": False,
    "role": None,
    "page": "Component Calculator"
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# LOGIN PAGE
# =========================================================
def login():

    st.markdown("""
        <style>
        .stApp {
            background: #f5f2eb;
            font-family: 'Segoe UI', sans-serif;
        }

        .block-container {
            padding-top: 0rem !important;
            padding-left: 2rem;
            padding-right: 2rem;
            padding-bottom: 0rem;
        }

        .left-box {
            text-align: center;
            margin-top: 120px;
            margin-left: 180px;
        }

        .title {
            font-size: 42px;
            margin-top: 3px;
            line-height: 1.2;
            color: #333;
            font-weight: 700;
        }

        .highlight {
            color: #f57c00;
        }

        .right-box {
            max-width: 460px;
            margin-top: 120px;
            margin-left: auto;
            margin-right: auto;
            background: transparent;
            padding: 10px;
            border-radius: 14px;
        }

        .heading {
            font-size: 28px;
            font-weight: 700;
        }

        .subtext {
            color: #666;
            margin-bottom: 25px;
        }

        .stTextInput>div>div>input {
            border-radius: 10px;
            height: 45px;
        }

        .stButton>button {
            background-color: #f57c00;
            color: white;
            height: 45px;
            border-radius: 10px;
            width: 150px;
            font-weight: 600;
            border: none;
        }

        section[data-testid="stSidebar"] {
            background: #ffffff;
        }

        div[data-testid="column"]:nth-of-type(2) {
            padding-top: 0rem !important;
        }
        </style>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown('<div class="left-box">', unsafe_allow_html=True)

        try:
            logo = remove_white_bg("logo.png")
            st.image(logo, width=220)
        except Exception:
            st.markdown("## OperaFlow")

        st.markdown("""
            <div class="title">
                OperaFlow <span class="highlight">Component</span>
            </div>
            <p style='font-size:18px;color:#666;'>
                Component Fabrication & Tracking System
            </p>
        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="right-box">', unsafe_allow_html=True)

        st.markdown(
            '<div class="heading">Sign in to your account</div>',
            unsafe_allow_html=True
        )

        st.markdown(
            '<div class="subtext">Authorized access only</div>',
            unsafe_allow_html=True
        )

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Sign In"):

            users = {
                "admin": {
                    "password": "admin@123",
                    "role": "admin"
                },
                "production": {
                    "password": "123",
                    "role": "production"
                },
                "preassembly": {
                    "password": "123",
                    "role": "preassembly"
                },
                "polishing": {
                    "password": "123",
                    "role": "polishing"
                },
                "final": {
                    "password": "123",
                    "role": "final"
                },
                "dispatch": {
                    "password": "123",
                    "role": "dispatch"
                }
            }

            if (
                username in users
                and users[username]["password"] == password
            ):
                st.session_state.logged_in = True
                st.session_state.role = users[username]["role"]
                st.session_state.page = "Component Calculator"

                st.success("Login successful")
                st.rerun()

            else:
                st.error("Invalid credentials")

        st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# LOGIN CHECK
# =========================================================
if not st.session_state.logged_in:
    login()
    st.stop()


# =========================================================
# DATABASE CONNECTION
# =========================================================
def create_connection():
    try:
        return psycopg2.connect(
            host=st.secrets["DB_HOST"],
            port=st.secrets["DB_PORT"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASSWORD"]
        )
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        return None


conn = create_connection()

if conn is None:
    st.stop()

cur = conn.cursor()


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:

    st.markdown("## OperaFlow")

    st.markdown(
        f"**Logged in as:** `{st.session_state.role.upper()}`"
    )

    st.markdown("---")

    if st.session_state.role == "admin":

        pages = [
            "Component Calculator",
            "Tracking",
            "Upload Data",
            "Product Master",
            "Delete Data"
        ]

    else:

        pages = [
            "Component Calculator",
            "Tracking"
        ]

    page = st.radio(
        "Navigation",
        pages
    )

    st.session_state.page = page

    st.markdown("---")

    if st.button("Logout", use_container_width=True):

        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.page = "Component Calculator"

        st.rerun()


# =========================================================
# ACCESS CONTROL
# =========================================================
page = st.session_state.page

admin_pages = [
    "Upload Data",
    "Delete Data"
]

if (
    st.session_state.role != "admin"
    and page in admin_pages
):
    st.error("Access denied")
    st.stop()


# =========================================================
# PAGE ROUTER
# =========================================================
try:

    if page == "Component Calculator":
        from component_calculator import show_component_calculator
        show_component_calculator(conn, cur)
    elif page == "Tracking":
        from tracking import show_tracking
        show_tracking(conn, cur)
    elif page == "Upload Data":
        from upload import show_upload
        show_upload(conn, cur)
    elif page == "Delete Data":
        from delete import show_delete
        show_delete(conn, cur)
    elif page == "Product Master":
        from product_master import show_product_master
        show_product_master(conn, cur)

except Exception as e:

    try:
        conn.rollback()
    except Exception:
        pass

    st.error(f"Error occurred: {e}")


finally:

    try:
        cur.close()
        conn.close()
    except Exception:
        pass
