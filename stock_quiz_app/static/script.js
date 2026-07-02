// Simplified Quiz Controller — Global Timer Model
document.addEventListener("DOMContentLoaded", () => {
    
    // Global showToast fallback if not defined in HTML
    if (typeof window.showToast !== 'function') {
        window.showToast = function(message, type = 'success') {
            const toast = document.createElement('div');
            toast.className = `toast-notification toast-${type}`;
            toast.innerHTML = `
                <div class="toast-content">
                    <span class="toast-icon">${type === 'success' ? '✓' : '✕'}</span>
                    <span class="toast-message">${message}</span>
                </div>
            `;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.style.animation = 'slideDown 0.3s ease-out reverse forwards';
                setTimeout(() => toast.remove(), 300);
            }, 4000);
        };
    }

    const quizContent = document.getElementById("quiz-content");
    if (!quizContent) return;

    let questions = [];
    let currentQuestionIndex = 0;
    let selectedAnswers = {};
    let timeRemaining = 30;
    let totalQuizTime = 30; // 30 seconds per question
    let totalTimeTaken = 0; // Track cumulative time across all questions
    let timerInterval = null;
    let quizActive = false;
    let backAttempts = 0;

    // ANTI-BACK BUTTON LOGIC
    history.pushState(null, document.title, location.href);
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

    // CHEAT PREVENTION & REFRESH PROTECTION LOGIC
    document.addEventListener("keydown", function (e) {
        if (quizActive) {
            // Prevent F5, Ctrl+R, Cmd+R
            if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r") || (e.metaKey && e.key.toLowerCase() === "r")) {
                e.preventDefault();
                triggerWarning("refresh");
                return;
            }
            
            // Prevent F12
            if (e.key === "F12") {
                e.preventDefault();
                showToast("Developer tools are disabled.", "error");
                return;
            }
            
            // Prevent Ctrl+Shift+I, J, C and Ctrl+U, S, P, A, C, V
            if (e.ctrlKey || e.metaKey) {
                const key = e.key.toLowerCase();
                if (e.shiftKey && ['i', 'j', 'c'].includes(key)) {
                    e.preventDefault();
                    showToast("Developer tools are disabled.", "error");
                    return;
                }
                if (['u', 's', 'p', 'a', 'c', 'v'].includes(key)) {
                    e.preventDefault();
                    showToast("Keyboard shortcuts are disabled during the quiz.", "error");
                    return;
                }
            }
        }
    });

    // Disable Right Click
    document.addEventListener('contextmenu', function(e) {
        if (quizActive) {
            e.preventDefault();
            showToast("Right-click is disabled.", "error");
        }
    });

    // Disable Copy/Cut
    document.addEventListener('copy', function(e) {
        if (quizActive) {
            e.preventDefault();
            showToast("Copying is disabled.", "error");
        }
    });
    document.addEventListener('cut', function(e) {
        if (quizActive) {
            e.preventDefault();
            showToast("Cutting is disabled.", "error");
        }
    });

    // Disable Text Selection and Dragging
    document.addEventListener('selectstart', function(e) {
        if (quizActive) {
            e.preventDefault();
        }
    });
    document.addEventListener('dragstart', function(e) {
        if (quizActive) {
            e.preventDefault();
        }
    });

    window.addEventListener("beforeunload", function (e) {
        if (quizActive) {
            e.preventDefault();
            e.returnValue = "Are you sure you want to leave? Your quiz will be auto-submitted.";
            return e.returnValue;
        }
    });

    window.addEventListener("pagehide", function (e) {
        if (quizActive) {
            // Fire and forget auto-submit as the page unloads
            const timeTaken = Math.max(1, totalTimeTaken);
            const submissionPayload = {
                answers: selectedAnswers,
                time_taken: timeTaken,
                warnings_count: warningsCount,
                quiz_id: 1,
                submitted_at: new Date().toISOString()
            };
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            
            fetch("/api/quiz/submit", {
                method: "POST",
                headers: { 
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify(submissionPayload),
                keepalive: true
            }).catch(() => {}); // Ignore catch since page is unloading
        }
    });

    // DOM Elements
    const questionEl = document.getElementById("question-text");
    const optionsGrid = document.getElementById("options-grid");
    const timerDisplay = document.getElementById("timer-display");
    const currentQDisplay = document.getElementById("current-q-num");
    const totalQDisplay = document.getElementById("total-q-num");
    const prevBtn = document.getElementById("prev-btn");
    const nextBtn = document.getElementById("next-btn");
    const progressBarFill = document.getElementById("progress-bar-fill");
    const dotsContainer = document.getElementById("question-dots");

    const quizWelcome = document.getElementById("quiz-welcome");
    const startQuizBtn = document.getElementById("start-quiz-btn");
    
    let warningsCount = 0;
    let lastWarningTime = 0;

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


    function triggerWarning(message) {
        if (!quizActive) return;
        
        const now = Date.now();
        if (now - lastWarningTime < 2000) return; // Prevent double trigger
        lastWarningTime = now;
        
        warningsCount++;
        
        if (warningsCount === 1) {
            showToast(`Warning 1: ${message}`, "error");
        } else if (warningsCount === 2) {
            showToast(`Warning 2: ${message} (Final Warning)`, "error");
        } else if (warningsCount >= 3) {
            showToast("Multiple violations detected. Auto-submitting quiz.", "error");
            submitQuiz();
        }
    }

    // FULLSCREEN LOGIC
    function handleFullscreenChange() {
        const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement;
        if (quizActive && !isFullscreen) {
            triggerWarning("fullscreen");
        }
    }
    
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
    document.addEventListener("msfullscreenchange", handleFullscreenChange);

    // TAB SWITCH / BLUR DETECTION
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === 'hidden') {
            triggerWarning("tab_switch");
        }
    });

    window.addEventListener("blur", () => {
        triggerWarning("blur");
    });

    // SCREENSHOT DETERRENCE (PrintScreen Key)
    document.addEventListener("keyup", function(e) {
        if (quizActive && e.key === "PrintScreen") {
            e.preventDefault();
            triggerWarning("screenshot");
            
            // Clear clipboard to deter pasting screenshots
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText("Screenshots are prohibited during the quiz.").catch(()=>{});
            }
        }
    });

    // DYNAMIC WATERMARK LOGIC
    function initWatermark() {
        const watermarkContainer = document.getElementById("quiz-watermark");
        if (!watermarkContainer) return;
        
        watermarkContainer.style.display = "flex";
        watermarkContainer.style.flexWrap = "wrap";
        watermarkContainer.innerHTML = "";
        
        const fullname = window.USER_FULLNAME || "Quiz Participant";
        const phone = window.USER_PHONE || "";
        
        // Create a 3x3 grid for the watermark
        for (let i = 0; i < 9; i++) {
            const wmBlock = document.createElement("div");
            wmBlock.style.width = "33.33%";
            wmBlock.style.height = "33.33%";
            wmBlock.style.display = "flex";
            wmBlock.style.flexDirection = "column";
            wmBlock.style.justifyContent = "center";
            wmBlock.style.alignItems = "center";
            wmBlock.style.opacity = "0.08";
            wmBlock.style.transform = "rotate(-25deg)";
            wmBlock.style.fontSize = "1.2rem";
            wmBlock.style.pointerEvents = "none";
            wmBlock.style.userSelect = "none";
            
            const nameEl = document.createElement("div");
            nameEl.textContent = fullname;
            
            const phoneEl = document.createElement("div");
            phoneEl.textContent = phone;
            
            const timeEl = document.createElement("div");
            timeEl.className = "wm-time";
            
            wmBlock.appendChild(nameEl);
            if (phone) wmBlock.appendChild(phoneEl);
            wmBlock.appendChild(timeEl);
            
            watermarkContainer.appendChild(wmBlock);
        }
        
        // Start time updater
        setInterval(() => {
            const nowStr = new Date().toLocaleString();
            document.querySelectorAll(".wm-time").forEach(el => {
                el.textContent = nowStr;
            });
        }, 1000);
    }

    function startQuizFlow() {
        if (quizWelcome) quizWelcome.style.display = "none";
        quizContent.style.display = "block";
        initWatermark();
        fetchQuiz();
    }

    const rulesModal = document.getElementById("quiz-rules-modal");
    const agreeRulesBtn = document.getElementById("agree-rules-btn");

    if (startQuizBtn && quizWelcome) {
        startQuizBtn.addEventListener("click", () => {
            // Show rules modal first
            if (rulesModal) {
                rulesModal.style.display = "flex";
            } else {
                startFullscreenAndQuiz();
            }
        });
    } else {
        // Fallback if welcome screen doesn't exist
        quizContent.style.display = "block";
        fetchQuiz();
    }
    
    if (agreeRulesBtn) {
        agreeRulesBtn.addEventListener("click", () => {
            if (rulesModal) rulesModal.style.display = "none";
            startFullscreenAndQuiz();
        });
    }

    function startFullscreenAndQuiz() {
        const elem = document.documentElement;
        const requestFS = elem.requestFullscreen || elem.webkitRequestFullscreen || elem.msRequestFullscreen;
        if (requestFS) {
            requestFS.call(elem).then(() => {
                startQuizFlow();
            }).catch(err => {
                showToast("Fullscreen is required to take the quiz.", "error");
                startQuizFlow(); // Still start if blocked
            });
        } else {
            startQuizFlow();
        }
    }

    if (prevBtn) {
        prevBtn.addEventListener("click", () => {
            // Backwards navigation disabled for strict 30s timer flow
            // if (currentQuestionIndex > 0) loadQuestion(currentQuestionIndex - 1);
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            if (selectedAnswers[questions[currentQuestionIndex].id] === undefined) {
                showToast("Please select an answer to proceed.", "error");
                return;
            }
            advanceQuestion();
        });
    }

    function advanceQuestion() {
        const timeSpentOnThis = Math.max(1, 30 - timeRemaining);
        totalTimeTaken += timeSpentOnThis;

        if (currentQuestionIndex === questions.length - 1) {
            submitQuiz();
        } else {
            loadQuestion(currentQuestionIndex + 1);
        }
    }

    async function fetchQuiz() {
        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            const response = await fetch("/api/quiz/start", {
                method: "POST",
                headers: { 
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                }
            });
            const data = await response.json();

            if (!data.success) {
                showToast(data.message || "Quiz currently closed or unavailable.", "error");
                window.location.href = "/dashboard";
                return;
            }

            questions = data.questions;
            
            // Restore saved state if exists
            if (data.saved_answers) {
                selectedAnswers = data.saved_answers;
            }
            if (data.saved_question_index !== undefined) {
                currentQuestionIndex = data.saved_question_index;
            }
            
            // Per-question timer initialization
            if (data.saved_answers && data.time_limit <= 30) {
                timeRemaining = data.time_limit;
            } else {
                timeRemaining = 30;
            }
            totalQuizTime = 30;
            
            totalQDisplay.textContent = questions.length;
            quizActive = true;
            
            loadQuestion(currentQuestionIndex);
            startTimer(); // Single global timer — never restarted per question
            startStatusPolling();
        } catch (e) {
            console.error("Failed to fetch quiz:", e);
            showToast("Failed to load quiz. Please check connection.", "error");
        }
    }
    
    let lastSaveTime = 0;
    let lastSavedState = "";
    async function saveProgress() {
        if (!quizActive) return;
        
        const currentState = JSON.stringify({
            ans: selectedAnswers,
            qIdx: currentQuestionIndex
        });
        
        if (currentState === lastSavedState) return; // Prevent unnecessary API calls
        
        const now = Date.now();
        if (now - lastSaveTime < 2000) return; // throttle 2 sec
        lastSaveTime = now;
        lastSavedState = currentState;
        
        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            await fetch("/api/quiz/save_progress", {
                method: "POST",
                headers: { 
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify({
                    answers: selectedAnswers,
                    current_question: currentQuestionIndex,
                    remaining_time: timeRemaining
                })
            });
        } catch (e) {
            console.warn("Failed to save progress:", e);
        }
    }

    let pollInterval = null;
    function startStatusPolling() {
        pollInterval = setInterval(async () => {
            if (!quizActive) {
                clearInterval(pollInterval);
                return;
            }
            try {
                const res = await fetch("/api/quiz/status");
                const data = await res.json();
                if (!data.is_active) {
                    showToast("The quiz has been closed by the admin. Submitting your current progress.", "error");
                    submitQuiz();
                }
            } catch (e) {
                console.warn("Status poll failed", e);
            }
        }, 10000);
    }

    function loadQuestion(index) {
        if (index < 0 || index >= questions.length) return;
        currentQuestionIndex = index;
        currentQDisplay.textContent = index + 1;

        // Reset timer to 30 for each new question
        timeRemaining = 30;

        const q = questions[index];
        questionEl.textContent = q.question;

        const progressPercent = (index / questions.length) * 100;
        progressBarFill.style.width = `${progressPercent}%`;

        if (dotsContainer) {
            dotsContainer.innerHTML = "";
            questions.forEach((qd, i) => {
                const dot = document.createElement("div");
                dot.className = "qdot";
                if (i === index) dot.classList.add("curr");
                else if (selectedAnswers[qd.id] !== undefined) dot.classList.add("done");
                
                // Disable jumping around by removing the click listener
                // dot.addEventListener("click", () => loadQuestion(i));
                
                dotsContainer.appendChild(dot);
            });
        }

        optionsGrid.innerHTML = "";
        const frag = document.createDocumentFragment();
        q.options.forEach((opt) => {
            const card = document.createElement("div");
            card.className = "option";
            if (selectedAnswers[q.id] === opt.index) card.classList.add("sel");

            card.innerHTML = `
                <div class="opt-badge">${getLetter(opt.index)}</div>
                <div class="opt-txt">${escapeHTML(opt.text)}</div>
            `;

            card.addEventListener("click", () => {
                selectedAnswers[q.id] = opt.index;
                document.querySelectorAll(".option").forEach(el => el.classList.remove("sel"));
                card.classList.add("sel");
                nextBtn.disabled = false;

                if (dotsContainer) {
                    const dots = dotsContainer.querySelectorAll(".qdot");
                    if (dots[index]) dots[index].classList.add("done");
                }
                
                saveProgress(); // Save to server on selection
            });
            frag.appendChild(card);
        });
        optionsGrid.appendChild(frag);

        prevBtn.style.display = "none";
        nextBtn.textContent = index === questions.length - 1 ? "Submit Quiz" : "Next Question";
        nextBtn.disabled = selectedAnswers[q.id] === undefined;
        
        // Save progress on question navigation
        saveProgress();
    }

    function getLetter(index) {
        const letters = { 1: "A", 2: "B", 3: "C", 4: "D" };
        return letters[index] || "•";
    }

    function startTimer() {
        updateTimerDisplay();
        timerInterval = setInterval(() => {
            timeRemaining--;
            updateTimerDisplay();

            if (timeRemaining <= 5) timerDisplay.classList.add("warning");
            else timerDisplay.classList.remove("warning");
            
            if (timeRemaining % 10 === 0) saveProgress(); // save every 10 seconds

            if (timeRemaining <= 0) {
                // Time expired for this question, auto skip or submit
                showToast("Time has expired for this question!", "error");
                
                // Set invalid answer so they get 0 points, then advance
                const q = questions[currentQuestionIndex];
                if (selectedAnswers[q.id] === undefined) {
                    selectedAnswers[q.id] = -1; // -1 means skipped
                }
                
                advanceQuestion();
            }
        }, 1000);
    }

    function updateTimerDisplay() {
        const mins = Math.max(0, Math.floor(timeRemaining / 60));
        const secs = Math.max(0, timeRemaining % 60);
        timerDisplay.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

        const timerArc = document.getElementById("timer-arc");
        if (timerArc && totalQuizTime > 0) {
            const percentRemaining = Math.max(0, Math.min(1, timeRemaining / totalQuizTime));
            const offset = 125.6 * (1 - percentRemaining);
            timerArc.setAttribute("stroke-dashoffset", offset);
        }
    }

    async function submitQuiz(isDisqualified = false) {
        if (!quizActive) return;
        quizActive = false;
        clearInterval(timerInterval);
        if (pollInterval) clearInterval(pollInterval);

        if (!isDisqualified) {
            nextBtn.disabled = true;
            nextBtn.textContent = "Submitting answers...";
        }

        // Send total cumulative time taken for all questions
        const timeTaken = Math.max(1, totalTimeTaken);

        const submissionPayload = {
            answers: selectedAnswers,
            time_taken: timeTaken,
            warnings_count: warningsCount,
            quiz_id: 1,
            submitted_at: new Date().toISOString()
        };

        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            const response = await fetch("/api/quiz/submit", {
                method: "POST",
                headers: { 
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify(submissionPayload)
            });
            const data = await response.json();

            if (data.success) {
                const redir = data.needs_phone 
                    ? `/reward_verification?score=${data.score}&total=${data.total}&time=${data.time_taken}`
                    : `/dashboard?submitted=true&score=${data.score}&total=${data.total}&time=${data.time_taken}`;
                
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
                    window.location.href = "/dashboard";
                }
            }
        } catch (err) {
            console.error("Submission failed:", err);
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
                nextBtn.textContent = "Submit Quiz";
                quizActive = true;
            }
        }
    }

    window.addEventListener('decoder:quiz_status_changed', function(e) {
        if (!e.detail.is_active && quizActive) {
            showDisqualificationModal("Auto Submitted", "The quiz has been CLOSED by the admin. Submitting your current progress.");
            setTimeout(() => submitQuiz(true), 1500);
        }
    });

    function escapeHTML(str) {
        return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
});
