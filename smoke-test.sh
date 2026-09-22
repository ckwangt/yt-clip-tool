#!/usr/bin/env bash
# Smoke test for the deployed /process endpoint.
# Hits a couple of known videos and checks the response for the failure
# modes we've hit before (bad format selection, HLS timeouts, missing
# subtitles, broken screenshots), then prints a PASS/FAIL summary.
#
# Usage: ./smoke-test.sh [base_url]
#   base_url defaults to the production server.

set -u

BASE_URL="${1:-http://34.127.52.76:5000}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

# Track how many /process calls and save-button clicks this run actually
# made, so the /admin counter check at the end knows how much the numbers
# should have moved by (see run_admin_counter_check).
GENERATE_CALLS_MADE=0
SAVE_CLICKS_MADE=0

# run_case <name> <youtube_url> <start> <end> <subtitle_mode>
# subtitle_mode: "none"    -> expect the "no subtitles" placeholder
#                "present" -> expect real, non-empty subtitle text
run_case() {
  local name="$1" url="$2" start="$3" end="$4" subtitle_mode="$5"
  local html="$TMP_DIR/${name// /_}.html"
  local case_fail=""

  local http_code
  http_code=$(curl -s -o "$html" -w "%{http_code}" --max-time 90 -X POST "$BASE_URL/process" \
    -d "youtube_url=$url" -d "start_time=$start" -d "end_time=$end" -d "lang=en")
  GENERATE_CALLS_MADE=$((GENERATE_CALLS_MADE + 1))

  if [ "$http_code" != "200" ]; then
    case_fail="HTTP status was $http_code, expected 200"
  fi

  if [ -z "$case_fail" ] && grep -q 'class="error-box"' "$html"; then
    local err_msg
    err_msg=$(grep -o 'class="error-box">[^<]*' "$html" | sed 's/^[^>]*>//')
    case_fail="error-box present: $err_msg"
  fi

  local download_name=""
  if [ -z "$case_fail" ]; then
    download_name=$(grep -o 'download="[^"]*"' "$html" | head -1 | sed 's/download="//;s/"$//')
    if [ -z "$download_name" ]; then
      case_fail="no download filename found in response"
    fi
  fi

  local subtitle_text=""
  if [ -z "$case_fail" ]; then
    subtitle_text=$(sed -n 's/.*id="subtitle-text">\(.*\)<\/div>.*/\1/p' "$html" | head -1)
    if [ "$subtitle_mode" = "none" ]; then
      if [[ "$subtitle_text" != *"No subtitles available"* ]]; then
        case_fail="expected the no-subtitles placeholder, got: $subtitle_text"
      fi
    else
      if [ -z "$subtitle_text" ] || [[ "$subtitle_text" == *"No subtitles available"* ]] || [[ "$subtitle_text" == *"Failed to fetch subtitles"* ]]; then
        case_fail="expected real subtitle text, got: $subtitle_text"
      fi
    fi
  fi

  local frame_url=""
  if [ -z "$case_fail" ]; then
    frame_url=$(grep -o 'src="/outputs/[^"]*"' "$html" | head -1 | sed 's/src="//;s/"$//')
    if [ -z "$frame_url" ]; then
      case_fail="no screenshot <img> src found in response"
    fi
  fi

  if [ -z "$case_fail" ]; then
    local img_file="$TMP_DIR/${name// /_}.jpg"
    local img_http_code
    img_http_code=$(curl -s -o "$img_file" -w "%{http_code}" --max-time 30 "$BASE_URL$frame_url")
    if [ "$img_http_code" != "200" ]; then
      case_fail="screenshot download returned HTTP $img_http_code"
    else
      local file_type
      file_type=$(file -b "$img_file" 2>/dev/null)
      if [[ "$file_type" != *"JPEG image data"* ]]; then
        case_fail="downloaded screenshot is not a valid JPEG (file: $file_type)"
      fi
    fi
  fi

  # Also exercise the actual "Save image as..." button (the ?dl= URL, not
  # the plain <img src>) — this is what a real click does, and it's what
  # logs a save_as event server-side (see run_admin_counter_check).
  local download_url=""
  if [ -z "$case_fail" ]; then
    download_url=$(grep -o 'href="/outputs/[^"]*"' "$html" | head -1 | sed 's/href="//;s/"$//')
    if [ -z "$download_url" ]; then
      case_fail="no save-button href found in response"
    fi
  fi

  if [ -n "$download_url" ]; then
    local dl_headers="$TMP_DIR/${name// /_}_dl_headers.txt"
    local dl_http_code
    dl_http_code=$(curl -s -o /dev/null -D "$dl_headers" -w "%{http_code}" --max-time 30 "$BASE_URL$download_url")
    SAVE_CLICKS_MADE=$((SAVE_CLICKS_MADE + 1))
    if [ -z "$case_fail" ]; then
      if [ "$dl_http_code" != "200" ]; then
        case_fail="save-button click returned HTTP $dl_http_code"
      elif ! grep -qi '^Content-Disposition:.*attachment' "$dl_headers"; then
        case_fail="save-button response missing Content-Disposition: attachment header"
      fi
    fi
  fi

  if [ -z "$case_fail" ]; then
    echo "PASS  $name  (download=\"$download_name\")"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL  $name -- $case_fail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("$name: $case_fail")
  fi
}

# run_admin_checks
# Verifies /admin responds sanely regardless of whether ADMIN_PASSWORD is set
# on the server. Never hardcodes credentials (this script is committed and
# also run against production) — if the caller exports ADMIN_USER/
# ADMIN_PASSWORD in their own shell before invoking this script, the
# authenticated checks run too; otherwise they're skipped.
run_admin_checks() {
  local name="/admin dashboard"
  local case_fail=""

  local noauth_headers="$TMP_DIR/admin_noauth_headers.txt"
  local noauth_code
  noauth_code=$(curl -s -o /dev/null -D "$noauth_headers" -w "%{http_code}" --max-time 30 "$BASE_URL/admin")

  if [ "$noauth_code" = "200" ]; then
    : # open dashboard (no ADMIN_PASSWORD set on the server) — fine for dev
  elif [ "$noauth_code" = "401" ]; then
    if ! grep -qi '^WWW-Authenticate:' "$noauth_headers"; then
      case_fail="got 401 but no WWW-Authenticate header (Basic Auth challenge looks broken)"
    fi
  else
    case_fail="unauthenticated GET /admin returned HTTP $noauth_code (expected 200 or 401)"
  fi

  if [ -z "$case_fail" ] && [ "$noauth_code" = "401" ]; then
    local wrong_code
    wrong_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 -u "notarealuser:notarealpass" "$BASE_URL/admin")
    if [ "$wrong_code" != "401" ]; then
      case_fail="wrong credentials returned HTTP $wrong_code, expected 401"
    fi
  fi

  if [ -z "$case_fail" ] && [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    local authed_html="$TMP_DIR/admin_authed.html"
    local authed_code
    authed_code=$(curl -s -o "$authed_html" -w "%{http_code}" --max-time 30 -u "$ADMIN_USER:$ADMIN_PASSWORD" "$BASE_URL/admin")
    if [ "$authed_code" != "200" ]; then
      case_fail="correct credentials returned HTTP $authed_code, expected 200"
    elif ! grep -q "Generate clicks" "$authed_html"; then
      case_fail="authenticated /admin response is missing expected dashboard content"
    fi
  elif [ -z "$case_fail" ] && [ "$noauth_code" = "401" ]; then
    name="$name (skipped authenticated-content check: set ADMIN_USER/ADMIN_PASSWORD env vars to also verify correct-credentials access)"
  fi

  if [ -z "$case_fail" ]; then
    echo "PASS  $name"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL  $name -- $case_fail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("$name: $case_fail")
  fi
}

# fetch_admin_counts
# Prints "<generate_total> <save_as_total>" and returns 0 if /admin was
# readable (with ADMIN_USER/ADMIN_PASSWORD if set, otherwise unauthenticated);
# returns 1 if it couldn't be read (e.g. auth-protected and no creds given).
fetch_admin_counts() {
  local html="$TMP_DIR/admin_counts_$RANDOM.html"
  local code
  if [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    code=$(curl -s -o "$html" -w "%{http_code}" --max-time 30 -u "$ADMIN_USER:$ADMIN_PASSWORD" "$BASE_URL/admin")
  else
    code=$(curl -s -o "$html" -w "%{http_code}" --max-time 30 "$BASE_URL/admin")
  fi
  [ "$code" = "200" ] || return 1
  local gen save
  gen=$(grep -A1 'Generate clicks' "$html" | grep -o '[0-9]\+' | head -1)
  save=$(grep -A1 'Save image as... clicks' "$html" | grep -o '[0-9]\+' | head -1)
  [ -n "$gen" ] && [ -n "$save" ] || return 1
  echo "$gen $save"
}

# run_admin_counter_check
# Confirms /admin's counters moved by at least as much as the generate/save
# calls this run actually made. Uses ">=" rather than "==" since this may run
# against production, where real users can add their own events concurrently.
run_admin_counter_check() {
  local name="/admin counters reflect this run's generate + save events"
  local case_fail=""
  local after
  if ! after=$(fetch_admin_counts); then
    case_fail="could not re-fetch /admin stats to verify counters moved"
  else
    local after_gen after_save
    after_gen=$(echo "$after" | awk '{print $1}')
    after_save=$(echo "$after" | awk '{print $2}')
    local expected_gen=$((BASELINE_GENERATE + GENERATE_CALLS_MADE))
    local expected_save=$((BASELINE_SAVE + SAVE_CLICKS_MADE))
    if [ "$after_gen" -lt "$expected_gen" ]; then
      case_fail="generate_total went from $BASELINE_GENERATE to $after_gen after $GENERATE_CALLS_MADE /process calls; expected at least $expected_gen"
    elif [ "$after_save" -lt "$expected_save" ]; then
      case_fail="save_as_total went from $BASELINE_SAVE to $after_save after $SAVE_CLICKS_MADE save-button clicks; expected at least $expected_save"
    fi
  fi

  if [ -z "$case_fail" ]; then
    echo "PASS  $name"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL  $name -- $case_fail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("$name: $case_fail")
  fi
}

echo "Smoke testing $BASE_URL ..."
echo

BASELINE_GENERATE=0
BASELINE_SAVE=0
ADMIN_BASELINE_OK=0
if baseline=$(fetch_admin_counts); then
  ADMIN_BASELINE_OK=1
  BASELINE_GENERATE=$(echo "$baseline" | awk '{print $1}')
  BASELINE_SAVE=$(echo "$baseline" | awk '{print $2}')
fi

run_case "ZhjqwrcdEpw (no captions, HLS-timeout repro)" \
  "https://www.youtube.com/watch?v=ZhjqwrcdEpw" "10" "20" "none"

run_case "5MuIMqhT8DM (has YouTube captions)" \
  "https://www.youtube.com/watch?v=5MuIMqhT8DM" "10" "20" "present"

run_admin_checks

if [ "$ADMIN_BASELINE_OK" = "1" ]; then
  run_admin_counter_check
fi

echo
if [ "$FAIL_COUNT" -eq 0 ]; then
  echo "RESULT: ALL PASS ($PASS_COUNT/$((PASS_COUNT + FAIL_COUNT)))"
  exit 0
else
  echo "RESULT: FAIL ($FAIL_COUNT/$((PASS_COUNT + FAIL_COUNT)) failed)"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
fi
