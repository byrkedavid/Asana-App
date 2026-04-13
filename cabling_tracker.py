import requests
import os
from dotenv import load_dotenv
import streamlit as st
import re
import base64

load_dotenv()

def get_config_value(name, default=None):
    if name in st.secrets:
        return st.secrets[name]
    return os.getenv(name, default)

ASANA_TOKEN = get_config_value("ASANA_TOKEN")
OPENAI_API_KEY = get_config_value("OPENAI_API_KEY")
OPENAI_VISION_MODEL = get_config_value("OPENAI_VISION_MODEL", "gpt-4.1-mini")
WORKSPACE_ID = "1214051352006115"
PROJECT_ID = "1214024107011760"

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

FIELD_IDS = {
    "fiber_ran": "1214032515160799",
    "copper_ran": "1214032515160803",
    "runners": "1214032515160807",
    "atl_site": "1214032515160809",
    "brick_patcher": "1214032515160839",
    "fusion_patcher": "1214032515160841",
    "brick_patched": "1214032515160843",
    "fusion_patched": "1214032515160847",
}

ENUM_IDS = {
    "fiber_ran": {
        "Yes": "1214032515160800",
        "No": "1214032515160801",
    },
    "copper_ran": {
        "Yes": "1214032515160804",
        "No": "1214032515160805",
    },
    "brick_patched": {
        "Patched": "1214032515160844",
        "Not Patched": "1214032515160845",
    },
    "fusion_patched": {
        "Patched": "1214032515160848",
        "Not Patched": "1214032515160849",
    },
}


## Find tasks

def find_task_by_name(position):
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}/tasks",
        headers=headers,
        params={
            "opt_fields": "gid,name",
            "limit": 100,
        },
    )
    response.raise_for_status()
    tasks = response.json()["data"]

    for task in tasks:
        if task["name"] == position:
            return task["gid"]

    return None


## Fetch users
def fetch_display_users():
    response = requests.get(
        f"https://app.asana.com/api/1.0/workspaces/{WORKSPACE_ID}/users",
        headers=headers,
        params={"opt_fields": "gid,name,email"},
    )
    response.raise_for_status()
    users = response.json()["data"]

    display_users = []
    user_lookup = {}

    for user in users:
        gid = user["gid"]
        name = user.get("name", "").strip()
        email = user.get("email", "").strip().lower()

        if name:
            display_users.append(name)
            user_lookup[name.lower()] = gid
        if email:
            user_lookup[email] = gid
            user_lookup[email.split("@")[0]] = gid

    display_users = sorted(set(display_users))
    return display_users, user_lookup

DISPLAY_USERS, USER_IDS = fetch_display_users()

def people_values(names):
    if not names:
        return None
    
    gids = []
    for name in names:
        key = name.strip().lower()
        if key not in USER_IDS:
            raise ValueError(f"Unknown user: {name}")
        gids.append(USER_IDS[key])

    return gids

def update_task(position, site, fiber_ran, copper_ran, brick_patched, fusion_patched, runners, brick_patcher, fusion_patcher):
    custom_fields = {
        FIELD_IDS["atl_site"]: SITE_OPTIONS[site],
        FIELD_IDS["fiber_ran"]: ENUM_IDS["fiber_ran"][fiber_ran],
        FIELD_IDS["copper_ran"]: ENUM_IDS["copper_ran"][copper_ran],
    }

    if brick_patched:
        custom_fields[FIELD_IDS["brick_patched"]] = ENUM_IDS["brick_patched"][brick_patched]

    if fusion_patched:
        custom_fields[FIELD_IDS["fusion_patched"]] = ENUM_IDS["fusion_patched"][fusion_patched]
        

    runner_value = people_values(runners)
    brick_patcher_value = people_values(brick_patcher)
    fusion_patcher_value = people_values(fusion_patcher)

    if runner_value is not None:
        custom_fields[FIELD_IDS["runners"]] = runner_value
    if brick_patcher_value is not None:
        custom_fields[FIELD_IDS["brick_patcher"]] = brick_patcher_value
    if fusion_patcher_value is not None:
        custom_fields[FIELD_IDS["fusion_patcher"]] = fusion_patcher_value


    task_gid = find_task_by_name(position)
    if not task_gid:
        raise ValueError(f"Task not found: {position}")

    payload = {
        "data": {
            "custom_fields": custom_fields,
        }
    }

    response = requests.put(
        f"https://app.asana.com/api/1.0/tasks/{task_gid}",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def get_site_options():
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}",
        headers=headers,
        params={
            "opt_fields": "custom_field_settings.custom_field.name,custom_field_settings.custom_field.enum_options.name,custom_field_settings.custom_field.enum_options.gid"
        },
    )
    response.raise_for_status()
    project = response.json()["data"]

    site_map = {}
    for setting in project.get("custom_field_settings", []):
        field = setting.get("custom_field", {})
        if field.get("name") == "ATL Site":
            for option in field.get("enum_options", []):
                site_map[option["name"]] = option["gid"]

    return site_map


def get_existing_task_names():
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}/tasks",
        headers=headers,
        params={"opt_fields": "name", "limit": 100},
    )
    response.raise_for_status()
    tasks = response.json()["data"]
    return {task["name"] for task in tasks}


def response_output_text(response_data):
    if response_data.get("output_text"):
        return response_data["output_text"]

    output_parts = []
    for item in response_data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                output_parts.append(content["text"])

    return "\n".join(output_parts)


def normalize_position_lines(raw_text):
    matches = re.findall(
        r"\b\d{2}\s*[-\u2013\u2014]\s*\d{2}\s*[-\u2013\u2014]\s*\d{3}\s*[-\u2013\u2014]\s*\d{2,3}\b",
        raw_text,
    )
    positions = []
    seen = set()

    for match in matches:
        parts = re.findall(r"\d+", match)
        if len(parts) != 4:
            continue
        position = f"{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"
        if position not in seen:
            positions.append(position)
            seen.add(position)

    return "\n".join(positions)


def extract_positions_from_image(image_file):
    if not OPENAI_API_KEY:
        raise ValueError("Add OPENAI_API_KEY to your .env file to use photo OCR.")

    image_bytes = image_file.getvalue()
    mime_type = image_file.type or "image/jpeg"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    prompt = (
        "Read the handwritten cabling position numbers in this image. "
        "Return only valid position numbers, one per line, using the format "
        "NN-NN-NNN-NN or NN-NN-NNN-NNN. Do not include the site prefix, bullets, "
        "extra words, or guesses that do not match that format."
    )

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_VISION_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded_image}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            "max_output_tokens": 500,
        },
        timeout=60,
    )
    response.raise_for_status()

    extracted_text = response_output_text(response.json())
    positions = normalize_position_lines(extracted_text)
    if not positions:
        raise ValueError("No valid positions were found in the image.")

    return positions


def read_positions_from_file(uploaded_file):
    file_name = getattr(uploaded_file, "name", "")
    if uploaded_file.type == "text/plain" or file_name.lower().endswith(".txt"):
        raw_text = uploaded_file.getvalue().decode("utf-8")
        positions = normalize_position_lines(raw_text)
        if not positions:
            raise ValueError("No valid positions were found in the text file.")
        return positions

    return extract_positions_from_image(uploaded_file)


## Web App
st.title("Cabling Tracker")
st.text("Note: Settings will apply to all listed positions.")

SITE_OPTIONS = get_site_options()
parsed_positions = []
missing_positions = []

site = st.selectbox("Site", list(SITE_OPTIONS.keys()))

if "positions_text" not in st.session_state:
    st.session_state["positions_text"] = ""

with st.expander("Scan handwritten positions"):
    st.text("Take a photo on mobile or upload a clear image.")
    camera_image = st.camera_input("Take a photo")
    uploaded_positions_file = st.file_uploader(
        "Upload image or text file",
        type=["jpg", "jpeg", "png", "webp", "gif", "txt"],
    )
    positions_source = camera_image or uploaded_positions_file

    if st.button("Fill positions from photo/file", disabled=positions_source is None):
        try:
            st.session_state["positions_text"] = read_positions_from_file(positions_source)
            st.rerun()
        except Exception as e:
            st.error(str(e))

positions_text = st.text_area(
    "Positions (one per line)",
    key="positions_text",
    placeholder="e.g.\n01-01-002-06\n01-01-003-15",
)

def parse_positions(site, raw_text):
    positions = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if not re.fullmatch(r"\d{2}-\d{2}-\d{3}-\d{2,3}", cleaned):
            raise ValueError(f"Invalid position format: {cleaned}")
        positions.append(f"{site}.1-{cleaned}")
    return positions

if positions_text.strip():
    try:
        parsed_positions = parse_positions(site, positions_text)
        existing_names = get_existing_task_names()
        missing_positions = [p for p in parsed_positions if p not in existing_names]

        if missing_positions:
            st.error("These positions do not exist in Asana:")
            for pos in missing_positions:
                st.markdown(f"- {pos}")

    except Exception as e:
        st.error(str(e))

fiber_ran = st.radio("Fiber Ran", ["Yes", "No"], index=0, horizontal=True)
copper_ran = st.radio("Copper Ran", ["Yes", "No"], index=0, horizontal=True)
brick_patched = st.radio("Brick Patched", ["Patched", "Not Patched"], index=0, horizontal=True)
fusion_patched = st.radio("Fusion Patched", ["Patched", "Not Patched"], index=0, horizontal=True)
# fiber_ran = st.selectbox("Fiber Ran", ["No", "Yes"])
# copper_ran = st.selectbox("Copper Ran", ["No", "Yes"])
# brick_patched = st.selectbox("Brick Patched", ["-", "Patched", "Not Patched"])
#fusion_patched = st.selectbox("Fusion Patched", ["-", "Patched", "Not Patched"])

runners = st.multiselect("Runner(s)", DISPLAY_USERS)
brick_patcher = st.multiselect("Brick Patcher(s)", DISPLAY_USERS)
fusion_patcher = st.multiselect("Fusion Patcher(s)", DISPLAY_USERS)



submit_clicked = st.button("Submit", disabled=bool(missing_positions))

if submit_clicked:
    try:
        if brick_patched == "-":
            brick_patched = ""
        if fusion_patched == "-":
            fusion_patched = ""

        positions = parsed_positions

        results = []
        for position in positions:
            update_task(
                position,
                site,
                fiber_ran,
                copper_ran,
                brick_patched,
                fusion_patched,
                runners,
                brick_patcher,
                fusion_patcher
            )
            results.append(position)

        st.balloons()
        st.success(f"Updated {len(results)} tasks")
        with st.expander("View updated positions"):
            for pos in results:
                st.markdown(f"- {pos}")

    except Exception as e:
        st.error(str(e))

st.divider()
st.markdown("### Instructions")
st.markdown("""1. Select the site from the dropdown.
2. Paste the list of positions (one per line), or scan handwritten positions from the photo section. The format should be `XX-XX-XXX-XX` or `XX-XX-XXX-XXX` (e.g. `01-01-002-06`).
3. Fill out the fields for fiber/copper ran, patching status, and personnel.
4. Click Submit to apply the updates to all listed positions. Note that all positions must already exist as tasks in Asana, and the personnel names must match existing users.""")

st.markdown(
    """
    <style>
    .block-container {
        min-height: calc(100vh - 140px);
        display: flex;
        flex-direction: column;
    }
    .footer {
        margin-top: auto;
        padding: 0.5rem 0 20px 0;
        text-align: left;
        font-size: 0.9rem;
        color: inherit;
        background-color: inherit;
    }
    </style>
    <div class="footer">Made by <a href="https://www.davidbyrke.com">David Byrke</a>   </div>
    """,
    unsafe_allow_html=True,
)

# https://app.asana.com/1/1214051352006115/project/1214024107011760/list/1214024107245700
