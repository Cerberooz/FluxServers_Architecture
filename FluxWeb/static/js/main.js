document.addEventListener('DOMContentLoaded', () => {
    // Preloader Logic
    const hidePreloader = () => {
        setTimeout(() => {
            document.body.classList.add('loaded');
        }, 150);
    };

    if (document.readyState === 'complete') {
        hidePreloader();
    } else {
        window.addEventListener('load', hidePreloader);
        // Fallback in case load event already fired or fails
        setTimeout(hidePreloader, 3000);
    }

    document.addEventListener('submit', (e) => {
        // Don't show loader for AJAX forms that were already prevented
        if (e.defaultPrevented) return;

        const loader = document.getElementById('action-loader');
        if (loader) {
            loader.classList.add('active');
        }
    });

    window.addEventListener('pageshow', (e) => {
        const loader = document.getElementById('action-loader');
        if (loader) {
            loader.classList.remove('active');
        }
        if (e.persisted) {
            document.body.classList.add('loaded');
        }
    });

    // Theme Switcher
    const themeToggle = document.getElementById('theme-toggle');
    const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)');

    // Check for saved theme preference or use the system preference
    const currentTheme = localStorage.getItem('theme') || (prefersDarkScheme.matches ? 'dark' : 'light');
    if (currentTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }

    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            let theme = document.documentElement.getAttribute('data-theme');
            if (theme === 'dark') {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
            }
        });
    }

    // Mobile menu toggle
    const hamburger = document.querySelector('.hamburger');
    const navLinks = document.querySelector('.nav-links');

    if (hamburger) {
        hamburger.addEventListener('click', () => {
            navLinks.classList.toggle('active');
            hamburger.classList.toggle('is-active');
        });
    }

    // Dropdown toggle for mobile
    const dropdownTriggers = document.querySelectorAll('.dropdown-trigger');
    dropdownTriggers.forEach(trigger => {
        trigger.addEventListener('click', (e) => {
            if (window.innerWidth <= 992) {
                e.preventDefault();
                const parent = trigger.closest('.nav-dropdown');
                if (parent) {
                    parent.classList.toggle('active');
                    // Close other dropdowns
                    document.querySelectorAll('.nav-dropdown').forEach(d => {
                        if (d !== parent) d.classList.remove('active');
                    });
                }
            }
        });
    });

    // Navbar scroll effect
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', () => {
        // Normal scroll logic
        if (window.scrollY > 20) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });


    // Intersection Observer for scroll reveal
    const observerOptions = {
        threshold: 0.05,
        rootMargin: '0px 0px 50px 0px'
    };

    const revealElements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, .btn, .card, .plan-card, li, .hero-content, .logo, .social-links a');

    revealElements.forEach(el => {
        el.classList.add('reveal-text');
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    revealElements.forEach(el => {
        observer.observe(el);

        // Immediate check for elements already in view
        const rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight) {
            el.classList.add('revealed');
        }
    });

    // Chart Bar Animation Observer
    const chartBars = document.querySelectorAll('.chart-bar');
    const barObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animated');
                barObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.01 }); // Lower threshold for better mobile detection

    chartBars.forEach(bar => {
        barObserver.observe(bar);

        // Use a small delay to ensure layout is settled
        setTimeout(() => {
            const rect = bar.getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0) {
                bar.classList.add('animated');
            }
        }, 100);
    });



    // --- ADD TO CART LOGIC ---
    window.addToCart = async (planId, planName, planPrice, planGame) => {
        window.location.assign(`/plans/${planId}/customize`);
    };

    document.addEventListener('click', (event) => {
        const cartButton = event.target.closest('.plan-cart-action .cart-button');
        if (!cartButton) return;

        event.preventDefault();
        const action = cartButton.closest('.plan-cart-action');
        if (!action) return;

        const targetUrl = cartButton.getAttribute('href') || `/plans/${action.getAttribute('data-plan-id')}/customize`;
        cartButton.classList.add('is-adding-config');
        setTimeout(() => {
            window.location.assign(targetUrl);
        }, 850);
    });

    window.removeFromCart = (index) => {
        // Send AJAX request to remove item
        fetch(`/remove-from-cart/${index}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
            }
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    location.reload();
                }
            })
            .catch(error => console.error('Error:', error));
    };

    // Combined form logic handled above at line 268

    // Close modal on click outside
    window.addEventListener('click', (e) => {
        const orderModal = document.getElementById('orderModal');
        const paymentModal = document.getElementById('paymentModal');
        if (orderModal && e.target === orderModal && typeof closeOrderModal === 'function') closeOrderModal();
        if (paymentModal && e.target === paymentModal && typeof closePaymentModal === 'function') closePaymentModal();
    });

    // Combined form logic handled above at line 268
});



// 3. Starfield Background
const starfield = document.getElementById('starfield');
if (starfield) {
    const createStar = () => {
        const star = document.createElement('div');
        star.className = 'star';
        const size = Math.random() * 2 + 1;
        star.style.width = size + 'px';
        star.style.height = size + 'px';
        star.style.left = Math.random() * 100 + '%';
        star.style.top = Math.random() * 100 + '%';
        star.style.opacity = Math.random();
        star.style.animation = 'twinkle ' + (Math.random() * 3 + 2) + 's infinite alternate';
        starfield.appendChild(star);
    };

    for (let i = 0; i < 50; i++) {
        createStar();
    }
}
