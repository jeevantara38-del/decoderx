text = open('templates/dashboard.html', encoding='utf-8').read()
text = text.replace('</script>\n{% endblock %}', '''                newBtn.style.cursor = 'not-allowed';
                newBtn.disabled = true;
                newBtn.textContent = 'Waiting for Next Competition...';
                joinBtn.replaceWith(newBtn);
            }
        }
    });

    window.addEventListener('decoder:leaderboard_updated', function(e) {
        fetch('/api/leaderboard/data_dashboard')
            .then(res => res.text())
            .then(html => {
                const tbody = document.getElementById('dashboard-lb-body');
                if (tbody) tbody.innerHTML = html;
            });
    });

    window.addEventListener('decoder:participant_joined', function(e) {
        console.log("Participant joined:", e.detail.user);
    });
</script>
{% endblock %}''')
open('templates/dashboard.html', 'w', encoding='utf-8').write(text)
