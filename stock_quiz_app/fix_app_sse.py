import re
import os

app_path = "app.py"
with open(app_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add imports for SSE
if "from flask import Response, stream_with_context" not in content:
    content = content.replace("from flask import Flask", "from flask import Flask, Response, stream_with_context")

import time

sse_code = """
@app.route("/api/stream", methods=["GET"])
def api_stream():
    def event_stream():
        last_state = None
        # Loop for 15 seconds before closing to let Vercel refresh the connection gracefully
        for _ in range(15):
            try:
                db = get_db()
                cursor = db.cursor()
                
                cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
                settings = cursor.fetchone()
                
                cursor.execute("SELECT COUNT(DISTINCT user_id) as count FROM quiz_attempts")
                participant_count = cursor.fetchone()["count"] or 0
                
                cursor.execute("SELECT MAX(score) as max_score FROM quiz_attempts")
                row = cursor.fetchone()
                max_score = row["max_score"] if row and row["max_score"] is not None else 0
                
                is_active = False
                if settings and settings["is_active"] == 1:
                    if settings["end_time"]:
                        end_time_val = settings["end_time"]
                        end_time = end_time_val if isinstance(end_time_val, datetime) else datetime.fromisoformat(end_time_val)
                        if datetime.now() <= end_time:
                            is_active = True
                    else:
                        is_active = True
                        
                current_state = {
                    "is_active": is_active,
                    "time_limit": settings["time_limit"] if settings else 300,
                    "prize_pool": settings["prize_pool"] if settings else 0,
                    "admin_message": dict(settings).get("admin_message", "") if settings else "",
                    "participant_count": participant_count
                }
                
                if current_state != last_state:
                    yield f"data: {json.dumps(current_state)}\\n\\n"
                    last_state = current_state
                else:
                    yield f"data: {json.dumps({'ping': True})}\\n\\n"
            except Exception as e:
                logger.error(f"SSE Error: {e}")
            import time
            time.sleep(1.0)
            
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")
"""

# Replace the api_live_status function
# We will just replace it via regex since it's cleaner
import re
pattern = re.compile(r'@app\.route\("/api/live-status", methods=\["GET"\]\)\ndef api_live_status\(\):.*?return jsonify\(\{.*?\}\)', re.DOTALL)
content = pattern.sub(sse_code.strip(), content)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated app.py for SSE.")
