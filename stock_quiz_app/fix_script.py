text = open('static/script.js', encoding='utf-8').read()
text = text.replace('    function escapeHTML(str) {', '    window.addEventListener(\'decoder:quiz_status_changed\', function(e) {\n        if (!e.detail.is_active && quizActive) {\n            quizActive = false;\n            showToast(\'Quiz has been CLOSED by admin! Submitting current progress...\', \'error\');\n            setTimeout(submitQuiz, 1500);\n        }\n    });\n\n    function escapeHTML(str) {')
open('static/script.js', 'w', encoding='utf-8').write(text)
