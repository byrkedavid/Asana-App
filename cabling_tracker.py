import requests
import os
from dotenv import load_dotenv
import streamlit as st
import re
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageOps

load_dotenv()

def get_config_value(name, default=None):
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip():
        return env_value.strip()

    try:
        secret_value = st.secrets.get(name, default)
    except st.errors.StreamlitSecretNotFoundError:
        return default

    if isinstance(secret_value, str):
        secret_value = secret_value.strip()

    return secret_value or default

ASANA_TOKEN = get_config_value("ASANA_TOKEN")
OCR_SPACE_API_KEY = get_config_value("OCR_SPACE_API_KEY")
OCR_SPACE_ENGINE = get_config_value("OCR_SPACE_ENGINE", "2")
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

@st.cache_data(ttl=60)
def get_project_task_map():
    task_map = {}
    params = {
        "opt_fields": "gid,name",
        "limit": 100,
    }

    while True:
        response = requests.get(
            f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}/tasks",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        response_data = response.json()

        for task in response_data["data"]:
            task_map[task["name"]] = task["gid"]

        next_page = response_data.get("next_page")
        if not next_page:
            break

        params["offset"] = next_page["offset"]

    return task_map


def find_task_by_name(position):
    return get_project_task_map().get(position)


## Fetch users
@st.cache_data(ttl=300)
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

TEST_DISPLAY_USERS = [
    "Alex Morgan",
    "Bailey Chen",
    "Casey Brooks",
    "Drew Patel",
    "Emery Johnson",
    "Finley Garcia",
    "Harper Lewis",
    "Jordan Kim",
    "Kai Thompson",
    "Logan Rivera",
    "Morgan Taylor",
    "Quinn Anderson",
]

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

def update_task(position, site, fiber_ran, copper_ran, brick_patched, fusion_patched, runners, brick_patcher, fusion_patcher, task_gid=None):
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


    task_gid = task_gid or find_task_by_name(position)
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
    return set(get_project_task_map().keys())


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


def prepare_image_for_ocr_space(image_file):
    max_size_bytes = 700 * 1024
    image = Image.open(image_file)
    image = ImageOps.exif_transpose(image)

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    longest_side = max(image.size)
    if longest_side > 1200:
        scale = 1200 / longest_side
        new_size = (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    for quality in (80, 70, 60, 50, 40):
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_size_bytes:
            return buffer.getvalue(), "positions.jpg", "image/jpeg"

    while True:
        image = image.resize(
            (
                max(1, int(image.width * 0.85)),
                max(1, int(image.height * 0.85)),
            ),
            Image.Resampling.LANCZOS,
        )
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=40, optimize=True)
        if buffer.tell() <= max_size_bytes or max(image.size) <= 700:
            return buffer.getvalue(), "positions.jpg", "image/jpeg"


def extract_positions_from_image(image_file):
    if not OCR_SPACE_API_KEY:
        raise ValueError("Add OCR_SPACE_API_KEY to your .env file or Streamlit Secrets to use photo OCR.")

    image_bytes, file_name, mime_type = prepare_image_for_ocr_space(image_file)

    try:
        response = requests.post(
            "https://api.ocr.space/parse/image",
            headers={"apikey": OCR_SPACE_API_KEY},
            data={
                "language": "eng",
                "isOverlayRequired": "false",
                "detectOrientation": "true",
                "scale": "true",
                "OCREngine": OCR_SPACE_ENGINE,
            },
            files={"file": (file_name, image_bytes, mime_type)},
            timeout=120,
        )
    except requests.exceptions.ReadTimeout:
        raise ValueError(
            "OCR.space timed out while reading the image. Try again in a minute, "
            "or retake the photo closer to the paper with less background."
        )
    if response.status_code >= 400:
        raise ValueError(f"OCR.space request failed: {response.text}")

    response_data = response.json()
    if response_data.get("IsErroredOnProcessing"):
        errors = response_data.get("ErrorMessage") or response_data.get("ErrorDetails")
        if isinstance(errors, list):
            errors = " ".join(errors)
        raise ValueError(f"OCR.space request failed: {errors}")

    extracted_text = "\n".join(
        result.get("ParsedText", "")
        for result in response_data.get("ParsedResults", [])
    )
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
if "positions_file_version" not in st.session_state:
    st.session_state["positions_file_version"] = 0

with st.expander("Scan handwritten positions"):
    st.text("Take a photo on mobile or upload a clear image.")
    uploaded_positions_file = st.file_uploader(
        "Upload image or text file",
        type=["jpg", "jpeg", "png", "webp", "gif", "txt"],
        key=f"positions_file_{st.session_state['positions_file_version']}",
    )
    positions_source = uploaded_positions_file

    if st.button("Fill positions from photo/file", disabled=positions_source is None):
        try:
            with st.spinner("Reading positions from image..."):
                st.session_state["positions_text"] = read_positions_from_file(positions_source)
            st.session_state["positions_file_version"] += 1
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

show_test_users = st.checkbox("Show test users", help="Adds fake names for testing the mobile people picker.")
people_options = DISPLAY_USERS
if show_test_users:
    people_options = sorted(set(DISPLAY_USERS + TEST_DISPLAY_USERS))
    st.caption("Test users are only for picker testing. Do not submit with test users selected.")

runners = st.multiselect("Runner(s)", people_options)
brick_patcher = st.multiselect("Brick Patcher(s)", people_options)
fusion_patcher = st.multiselect("Fusion Patcher(s)", people_options)



submit_clicked = st.button("Submit", disabled=bool(missing_positions))

if submit_clicked:
    try:
        positions = parsed_positions
        if not positions:
            raise ValueError("Enter at least one position before submitting.")

        results = []
        errors = []
        task_map = get_project_task_map()
        max_workers = min(4, len(positions))

        with st.spinner(f"Updating {len(positions)} task(s) in Asana..."):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        update_task,
                        position,
                        site,
                        fiber_ran,
                        copper_ran,
                        brick_patched,
                        fusion_patched,
                        runners,
                        brick_patcher,
                        fusion_patcher,
                        task_map.get(position),
                    ): position
                    for position in positions
                }

                for future in as_completed(futures):
                    position = futures[future]
                    try:
                        future.result()
                        results.append(position)
                    except Exception as e:
                        errors.append(f"{position}: {e}")

        if errors:
            raise ValueError("Some updates failed:\n" + "\n".join(errors))

        st.session_state["last_submit_results"] = [
            position
            for position in positions
            if position in results
        ]
        st.session_state["positions_file_version"] += 1
        st.rerun()

    except Exception as e:
        st.error(str(e))

if "last_submit_results" in st.session_state:
    results = st.session_state.pop("last_submit_results")
    st.balloons()
    st.success(f"Updated {len(results)} tasks")
    with st.expander("View updated positions"):
        for pos in results:
            st.markdown(f"- {pos}")

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
    div[role="radiogroup"] {
        gap: 0.4rem;
    }
    div[role="radiogroup"] label {
        margin: 0;
        padding: 0.35rem 0.7rem;
        min-height: 2.4rem;
        border: 1px solid #8b919a;
        border-radius: 8px;
        background: #f0f2f6;
        color: var(--text-color);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    div[role="radiogroup"] label:has(input:checked) {
        border-color: rgb(255, 75, 75);
        background: rgb(255, 75, 75);
        color: #ffffff;
    }
    div[role="radiogroup"] label > div:first-child {
        display: none;
    }
    div[role="radiogroup"] label > div {
        padding: 0;
    }
    div[role="radiogroup"] label p {
        margin: 0;
        padding: 0;
        line-height: 1.2;
        color: inherit;
    }
    @media (prefers-color-scheme: dark) {
        div[role="radiogroup"] label {
            border-color: rgba(250, 250, 250, 0.3);
            background: rgba(250, 250, 250, 0.14);
            color: rgb(250, 250, 250);
        }
    }
    #MainMenu,
    footer,
    header,
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    [data-testid="stDeployButton"] {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    <div class="footer">Made by <a href="https://www.davidbyrke.com">David Byrke</a>   </div>
    """,
    unsafe_allow_html=True,
)

# https://app.asana.com/1/1214051352006115/project/1214024107011760/list/1214024107245700