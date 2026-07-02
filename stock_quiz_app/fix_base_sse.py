import re

html_path = "templates/base.html"
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

sse_code = """
        let sseReconnectTimer = null;
        function connectSSE() {
            const eventSource = new EventSource('/api/stream');
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.ping) return; // Keep-alive ping
                
                // 1. Quiz Status changes
                if (window.lastQuizStatus !== undefined && window.lastQuizStatus !== data.is_active) {
                    window.dispatchEvent(new CustomEvent('decoder:quiz_status_changed', { 
                        detail: { is_active: data.is_active, time_limit: data.time_limit }
                    }));
                }
                window.lastQuizStatus = data.is_active;

                // 2. Leaderboard or General state updates (since SSE sends full state we just fire it)
                window.dispatchEvent(new CustomEvent('decoder:leaderboard_updated', { 
                    detail: { participant_count: data.participant_count, prize_pool: data.prize_pool }
                }));

                // 3. Admin announcements
                if (data.admin_message && data.admin_message !== window.lastAdminMessage) {
                    window.dispatchEvent(new CustomEvent('decoder:admin_message', { 
                        detail: { message: data.admin_message }
                    }));
                    showToast(`📢 Admin Announcement: ${data.admin_message}`, "info");
                    window.lastAdminMessage = data.admin_message;
                }
            };
            
            eventSource.onerror = function() {
                eventSource.close();
                // Avoid flooding with reconnect messages, just silently reconnect for smooth Vercel experience
                if (!sseReconnectTimer) {
                    sseReconnectTimer = setTimeout(() => {
                        sseReconnectTimer = null;
                        connectSSE();
                    }, 2000);
                }
            };
        }
        // Start connection
        connectSSE();
"""

# Replace the block from `function pollLiveStatus() {` to `setInterval(pollLiveStatus, 2500);`
pattern = re.compile(r'function pollLiveStatus\(\) \{.*?setInterval\(pollLiveStatus,\s*2500\);', re.DOTALL)
content = pattern.sub(sse_code.strip(), content)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated base.html for SSE.")
