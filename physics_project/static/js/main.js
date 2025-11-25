// 主要JavaScript功能
document.addEventListener('DOMContentLoaded', function() {
    // 初始化工具提示
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // 表单提交按钮防重复点击
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 处理中...';
            }
        });
    });

    // 自动隐藏警告消息
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // 题目搜索和筛选功能
    const searchInput = document.getElementById('searchInput');
    const statusFilter = document.getElementById('statusFilter');
    const difficultyFilter = document.getElementById('difficultyFilter');

    if (searchInput && statusFilter && difficultyFilter) {
        function filterProblems() {
            const searchTerm = searchInput.value.toLowerCase();
            const statusValue = statusFilter.value;
            const difficultyValue = difficultyFilter.value;
            const problemCards = document.querySelectorAll('.problem-card');

            problemCards.forEach(card => {
                const name = card.getAttribute('data-name').toLowerCase();
                const status = card.getAttribute('data-status');
                const difficulty = card.getAttribute('data-difficulty');

                const matchesSearch = name.includes(searchTerm) ||
                                    card.textContent.toLowerCase().includes(searchTerm);
                const matchesStatus = statusValue === 'all' || status === statusValue;
                const matchesDifficulty = difficultyValue === 'all' || difficulty === difficultyValue;

                if (matchesSearch && matchesStatus && matchesDifficulty) {
                    card.style.display = 'block';
                    setTimeout(() => {
                        card.classList.add('fade-in');
                    }, 50);
                } else {
                    card.style.display = 'none';
                }
            });
        }

        searchInput.addEventListener('input', filterProblems);
        statusFilter.addEventListener('change', filterProblems);
        difficultyFilter.addEventListener('change', filterProblems);
    }

    // 刷新单个题目
    window.refreshSingleProblem = function(problemId) {
        if (confirm('确定要刷新这道题目吗？这将生成新的题目参数。')) {
            fetch(`/refresh_problem/${problemId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('刷新失败: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('刷新失败');
            });
        }
    }

    // 刷新所有题目
    window.refreshAllProblems = function() {
        if (confirm('确定要刷新所有题目吗？这将重新生成所有题目的参数。')) {
            fetch('/refresh_all_problems', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('刷新失败: ' + data.message);
                }
            });
        }
    }

    // 显示解析
    window.showSolution = function(problemId) {
        alert('解析功能开发中...');
    }

    // 添加键盘快捷键
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            if (typeof refreshAllProblems === 'function') {
                refreshAllProblems();
            }
        }
    });

    // MathJax配置
    window.MathJax = {
        tex: {
            inlineMath: [['$', '$'], ['\\(', '\\)']],
            displayMath: [['$$', '$$'], ['\\[', '\\]']]
        },
        svg: {
            fontCache: 'global'
        }
    };
});

// 页面加载动画
window.addEventListener('load', function() {
    document.body.classList.add('loaded');
});