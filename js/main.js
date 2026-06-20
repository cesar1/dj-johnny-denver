/**
 * DJ Johnny — main.js
 * djjohnnydenver.com
 */

document.addEventListener('DOMContentLoaded', () => {

  // ── NAV: add .scrolled class on scroll ──────────────────────────
  const nav = document.getElementById('main-nav');

  const handleNavScroll = () => {
    nav?.classList.toggle('scrolled', window.scrollY > 24);
  };

  window.addEventListener('scroll', handleNavScroll, { passive: true });
  handleNavScroll(); // run once on load


  // ── EQUALIZER BARS: generate random animated bars in hero ────────
  const eqContainer = document.querySelector('.hero__equalizer');

  if (eqContainer) {
    const BAR_COUNT = 72;

    for (let i = 0; i < BAR_COUNT; i++) {
      const bar = document.createElement('div');
      bar.className = 'eq-bar';

      const lo  = (Math.random() * 5  + 2).toFixed(1);
      const hi  = (Math.random() * 56 + 8).toFixed(1);
      const dur = (Math.random() * 0.55 + 0.38).toFixed(2);
      const d   = (Math.random() * 0.9).toFixed(2);

      bar.style.setProperty('--lo', `${lo}px`);
      bar.style.setProperty('--hi', `${hi}px`);
      bar.style.setProperty('--dur', `${dur}s`);
      bar.style.setProperty('--d', `${d}s`);

      // Occasional purple accent bars
      if (i % 9 === 0) {
        bar.style.background = 'var(--purple)';
      }

      eqContainer.appendChild(bar);
    }
  }


  // ── SCROLL REVEAL: IntersectionObserver for .reveal elements ────
  const revealEls = document.querySelectorAll('.reveal');

  if (revealEls.length > 0) {
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('in-view');
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
    );

    revealEls.forEach((el) => revealObserver.observe(el));
  }


  // ── SMOOTH SCROLL + mobile nav close ────────────────────────────
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener('click', (e) => {
      const targetId = link.getAttribute('href');
      if (targetId === '#') return;

      const target = document.querySelector(targetId);
      if (!target) return;

      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth' });

      // Close Bootstrap mobile nav if open
      const navCollapse = document.getElementById('navMenu');
      if (navCollapse?.classList.contains('show')) {
        const bsCollapse = bootstrap.Collapse.getInstance(navCollapse);
        bsCollapse?.hide();
      }
    });
  });


  // ── BOOKING FORM: validation + submit to booking API ─────────────
  // Public API Gateway endpoint (no secret — safe to commit).
  // Set this to the ApiEndpoint printed by `aws apigatewayv2 create-api`.
  // See infra/README.md for the full backend setup.
  const BOOKING_API_URL = 'https://REPLACE-ME.execute-api.us-east-1.amazonaws.com';

  const form       = document.getElementById('booking-form');
  const successMsg = document.getElementById('form-success');
  const errorMsg   = document.getElementById('form-error');

  if (form && successMsg) {

    // Prevent picking a past date in the event-date field
    const dateField = form.querySelector('#event-date');
    if (dateField) dateField.min = new Date().toISOString().split('T')[0];

    // Clear invalid state on user input
    form.querySelectorAll('.form-control').forEach((field) => {
      field.addEventListener('input', () => {
        field.classList.remove('is-invalid');
      });
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      successMsg.hidden = true;
      if (errorMsg) errorMsg.hidden = true;

      let isValid = true;

      // Required fields
      form.querySelectorAll('[required]').forEach((field) => {
        field.classList.remove('is-invalid');
        if (!field.value.trim()) {
          field.classList.add('is-invalid');
          isValid = false;
        }
      });

      // Email format
      const emailField = form.querySelector('#email');
      if (emailField?.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailField.value)) {
        emailField.classList.add('is-invalid');
        isValid = false;
      }

      if (!isValid) {
        // Scroll to first invalid field
        const firstInvalid = form.querySelector('.is-invalid');
        firstInvalid?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      // Submit to the booking API (API Gateway → Lambda → DynamoDB + SES)
      const submitBtn = form.querySelector('.btn--submit');
      const btnText   = submitBtn?.querySelector('.btn-text');
      const btnIcon   = submitBtn?.querySelector('.btn-icon');

      const setLoading = (loading) => {
        if (submitBtn) submitBtn.disabled = loading;
        if (btnText)   btnText.textContent = loading ? 'Enviando…' : 'Enviar Solicitud de Reserva';
        if (btnIcon)   btnIcon.style.opacity = loading ? '0.5' : '';
      };

      // Map form fields to the snake_case keys the Lambda expects.
      // `website` is the honeypot — always empty for real users.
      const payload = {
        name:       form.querySelector('#name').value.trim(),
        email:      form.querySelector('#email').value.trim(),
        phone:      form.querySelector('#phone').value.trim(),
        event_date: form.querySelector('#event-date').value,
        event_type: form.querySelector('#event-type').value,
        venue:      form.querySelector('#venue').value.trim(),
        message:    form.querySelector('#message').value.trim(),
        website:    form.querySelector('#website')?.value.trim() ?? '',
      };

      setLoading(true);

      try {
        const res = await fetch(BOOKING_API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) throw new Error(`Request failed: ${res.status}`);

        // Success — clear the form and confirm
        form.reset();
        form.querySelectorAll('.is-invalid').forEach((f) => f.classList.remove('is-invalid'));
        successMsg.hidden = false;
        successMsg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) {
        console.error('Booking submit failed:', err);
        if (errorMsg) {
          errorMsg.hidden = false;
          errorMsg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      } finally {
        setLoading(false);
      }
    });
  }

});
