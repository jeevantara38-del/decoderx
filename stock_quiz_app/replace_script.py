import re
import os

filepath = "static/script.js"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add tracking variables and modal logic
modal_logic = """
    let violationCounts = {
        fullscreen: 0,
        tab_switch: 0,
        blur: 0,
        screenshot: 0,
        devtools: 0,
        shortcut: 0,
        right_click: 0,
        copy: 0,
        cut: 0,
        refresh: 0,
        back: 0
    };

    const VIOLATION_MESSAGES = {
        fullscreen: "You exited fullscreen mode",
        tab_switch: "You switched browser tabs",
        blur: "You lost window focus",
        screenshot: "You attempted to take a screenshot",
        devtools: "You opened Developer Tools (F12/Inspect)",
        shortcut: "You used a restricted keyboard shortcut",
        right_click: "You attempted to right-click",
        copy: "You attempted to copy text",
        cut: "You attempted to cut text",
        refresh: "You attempted to refresh the page",
        back: "You pressed the browser Back button"
    };

    function showDisqualificationModal(status = "Auto Submitted", immediateReason = null) {
        document.getElementById("quiz-container").style.display = "none";
        
        let reasonHtml = "";
        let multiple = false;
        
        if (immediateReason) {
            reasonHtml += `<li>${immediateReason}</li>`;
        } else {
            let activeViolations = [];
            for (const [key, count] of Object.entries(violationCounts)) {
                if (count > 0) {
                    activeViolations.push(`<li>${VIOLATION_MESSAGES[key]} ${count} time(s).</li>`);
                }
            }
            if (activeViolations.length > 1) {
                reasonHtml += `<li>Multiple suspicious activities were detected.</li>`;
            }
            reasonHtml += activeViolations.join("");
        }

        const modal = document.createElement("div");
        modal.style.position = "fixed";
        modal.style.top = "0";
        modal.style.left = "0";
        modal.style.width = "100vw";
        modal.style.height = "100vh";
        modal.style.background = "rgba(0,0,0,0.85)";
        modal.style.backdropFilter = "blur(5px)";
        modal.style.zIndex = "10000";
        modal.style.display = "flex";
        modal.style.justifyContent = "center";
        modal.style.alignItems = "center";
        modal.style.padding = "20px";
        
        const timeStr = new Date().toLocaleTimeString();
        
        modal.innerHTML = `
            <div class="glass auth-card" style="max-width: 500px; width: 100%; padding: 30px; border: 1px solid rgba(255, 77, 109, 0.3); text-align: left;">
                <h2 style="color: #ff4d6d; margin-bottom: 20px; text-align: center; font-size: 1.8rem; font-family: 'Outfit', sans-serif;">Quiz ${status}</h2>
                
                <p style="color: var(--text-secondary); margin-bottom: 10px;"><strong>Status:</strong> <span style="color: #ff4d6d;">${status}</span></p>
                <p style="color: var(--text-secondary); margin-bottom: 10px;"><strong>Warnings Received:</strong> ${warningsCount}</p>
                <p style="color: var(--text-secondary); margin-bottom: 20px;"><strong>Time of Violation:</strong> ${timeStr}</p>
                
                <h3 style="color: white; margin-bottom: 10px; font-size: 1.2rem;">Reason:</h3>
                <ul style="color: #ff4d6d; line-height: 1.6; margin-bottom: 30px; padding-left: 20px;">
                    ${reasonHtml}
                </ul>
                
                <div style="text-align: center;">
                    <p style="color: var(--text-secondary); margin-bottom: 15px;" id="dq-status-text">Submitting your results...</p>
                    <button id="dq-continue-btn" class="btn-primary" style="width: 100%; padding: 15px; font-size: 1.1rem; opacity: 0.5; cursor: not-allowed;" disabled>Please wait</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        window.dqContinueBtn = document.getElementById("dq-continue-btn");
        window.dqStatusText = document.getElementById("dq-status-text");
        
        window.dqContinueBtn.addEventListener("click", () => {
            if (window.dqRedirectUrl) {
                window.location.href = window.dqRedirectUrl;
            }
        });
    }
"""

content = re.sub(
    r'let warningsCount = 0;\s*let lastWarningTime = 0;',
    r'let warningsCount = 0;\n    let lastWarningTime = 0;\n' + modal_logic,
    content
)

# Modify triggerWarning
new_trigger_warning = """
    function triggerWarning(type) {
        if (!quizActive) return;
        
        const now = Date.now();
        if (now - lastWarningTime < 2000) return; // Prevent double trigger
        lastWarningTime = now;
        
        warningsCount++;
        violationCounts[type] = (violationCounts[type] || 0) + 1;
        
        const msg = VIOLATION_MESSAGES[type] || "Suspicious activity detected";
        
        if (warningsCount === 1) {
            showToast(`Warning 1: ${msg}`, "error");
        } else if (warningsCount === 2) {
            showToast(`Warning 2: ${msg} (Final Warning)`, "error");
        } else if (warningsCount >= 3) {
            showDisqualificationModal("Disqualified");
            submitQuiz(true); // pass flag that we are auto-submitting via disqualification
        }
    }
"""
content = re.sub(
    r'function triggerWarning\(message\) \{.*?(?=\n    // FULLSCREEN LOGIC)/s',
    new_trigger_warning,
    content,
    flags=re.DOTALL
)

# Replace all calls to triggerWarning
content = content.replace('triggerWarning("You must remain in fullscreen.");', 'triggerWarning("fullscreen");')
content = content.replace('triggerWarning("Tab switching or minimizing the app is not allowed.");', 'triggerWarning("tab_switch");')
content = content.replace('triggerWarning("Window lost focus. Do not switch applications.");', 'triggerWarning("blur");')
content = content.replace('triggerWarning("Screenshots are prohibited.");', 'triggerWarning("screenshot");')
content = content.replace('triggerWarning("Developer tools are disabled.");', 'triggerWarning("devtools");')
content = content.replace('triggerWarning("Keyboard shortcuts are disabled during the quiz.");', 'triggerWarning("shortcut");')
content = content.replace('triggerWarning("Right-click is disabled.");', 'triggerWarning("right_click");')
content = content.replace('triggerWarning("Copying is disabled.");', 'triggerWarning("copy");')
content = content.replace('triggerWarning("Cutting is disabled.");', 'triggerWarning("cut");')

# Anti-back button logic
anti_back_old = """
    window.addEventListener('popstate', function (event) {
        if (quizActive) {
            history.pushState(null, document.title, location.href);
            backAttempts++;
            if (backAttempts >= 3) {
                showToast("Multiple attempts to leave detected. Auto-submitting quiz.", "error");
                submitQuiz();
            } else {
                showToast("Leaving the quiz is not allowed.", "error");
            }
        }
    });
"""
anti_back_new = """
    window.addEventListener('popstate', function (event) {
        if (quizActive) {
            history.pushState(null, document.title, location.href);
            backAttempts++;
            violationCounts['back'] = (violationCounts['back'] || 0) + 1;
            warningsCount++;
            if (backAttempts >= 3 || warningsCount >= 3) {
                showDisqualificationModal("Auto Submitted", "You pressed the browser Back button multiple times.");
                submitQuiz(true);
            } else {
                showToast("Leaving the quiz is not allowed.", "error");
            }
        }
    });
"""
content = content.replace(anti_back_old.strip(), anti_back_new.strip())


# Refresh logic
refresh_old = """
            if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r") || (e.metaKey && e.key.toLowerCase() === "r")) {
                e.preventDefault();
                showToast("Refresh is disabled during the quiz.", "error");
                return;
            }
"""
refresh_new = """
            if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r") || (e.metaKey && e.key.toLowerCase() === "r")) {
                e.preventDefault();
                triggerWarning("refresh");
                return;
            }
"""
content = content.replace(refresh_old.strip(), refresh_new.strip())

# submitQuiz changes
submit_quiz_old = """
    async function submitQuiz() {
        if (!quizActive) return;
        quizActive = false;
        clearInterval(timerInterval);
        if (pollInterval) clearInterval(pollInterval);

        nextBtn.disabled = true;
        nextBtn.textContent = "Submitting answers...";
"""

submit_quiz_new = """
    async function submitQuiz(isDisqualified = false) {
        if (!quizActive) return;
        quizActive = false;
        clearInterval(timerInterval);
        if (pollInterval) clearInterval(pollInterval);

        if (!isDisqualified) {
            nextBtn.disabled = true;
            nextBtn.textContent = "Submitting answers...";
        }
"""
content = content.replace(submit_quiz_old.strip(), submit_quiz_new.strip())


submit_response_old = """
            if (data.success) {
                if (data.needs_phone) {
                    window.location.href = `/reward_verification?score=${data.score}&total=${data.total}&time=${data.time_taken}`;
                } else {
                    window.location.href = `/success?score=${data.score}&total=${data.total}&time=${data.time_taken}`;
                }
            } else {
                showToast(data.message || "Failed to submit answers.", "error");
                nextBtn.disabled = false;
                nextBtn.textContent = "Next Question";
            }
        } catch (e) {
            showToast("Submission failed. Please check your connection and try again.", "error");
            nextBtn.disabled = false;
            nextBtn.textContent = "Next Question";
            quizActive = true;
        }
"""

submit_response_new = """
            if (data.success) {
                const redir = data.needs_phone 
                    ? `/reward_verification?score=${data.score}&total=${data.total}&time=${data.time_taken}`
                    : `/success?score=${data.score}&total=${data.total}&time=${data.time_taken}`;
                
                if (isDisqualified && window.dqContinueBtn) {
                    window.dqRedirectUrl = redir;
                    window.dqContinueBtn.disabled = false;
                    window.dqContinueBtn.style.opacity = "1";
                    window.dqContinueBtn.style.cursor = "pointer";
                    window.dqContinueBtn.textContent = "Continue to Results";
                    window.dqStatusText.textContent = "Results submitted successfully.";
                } else {
                    window.location.href = redir;
                }
            } else {
                if (isDisqualified && window.dqContinueBtn) {
                    window.dqStatusText.textContent = "Submission failed: " + (data.message || "Error");
                    window.dqContinueBtn.disabled = false;
                    window.dqContinueBtn.style.opacity = "1";
                    window.dqContinueBtn.style.cursor = "pointer";
                    window.dqContinueBtn.textContent = "Return to Dashboard";
                    window.dqRedirectUrl = "/dashboard";
                } else {
                    showToast(data.message || "Failed to submit answers.", "error");
                    nextBtn.disabled = false;
                    nextBtn.textContent = "Next Question";
                }
            }
        } catch (e) {
            if (isDisqualified && window.dqContinueBtn) {
                window.dqStatusText.textContent = "Network error. Failed to submit.";
                window.dqContinueBtn.disabled = false;
                window.dqContinueBtn.style.opacity = "1";
                window.dqContinueBtn.style.cursor = "pointer";
                window.dqContinueBtn.textContent = "Return to Dashboard";
                window.dqRedirectUrl = "/dashboard";
            } else {
                showToast("Submission failed. Please check your connection and try again.", "error");
                nextBtn.disabled = false;
                nextBtn.textContent = "Next Question";
                quizActive = true;
            }
        }
"""
content = content.replace(submit_response_old.strip(), submit_response_new.strip())

# Fix the server closing quiz message
server_close_old = """
        if (!e.detail.is_active && quizActive) {
            quizActive = false;
            showToast('Quiz has been CLOSED by admin! Submitting current progress...', 'error');
            setTimeout(submitQuiz, 1500);
        }
"""
server_close_new = """
        if (!e.detail.is_active && quizActive) {
            showDisqualificationModal("Auto Submitted", "The quiz has been CLOSED by the admin. Submitting your current progress.");
            setTimeout(() => submitQuiz(true), 1500);
        }
"""
content = content.replace(server_close_old.strip(), server_close_new.strip())


with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
