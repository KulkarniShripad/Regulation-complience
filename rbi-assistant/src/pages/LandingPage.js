import React, { useEffect, useRef } from 'react';
import './LandingPage.css';

const FEATURES = [
  {
    icon: '⚖️',
    title: 'AI-Powered Chat',
    desc: 'Ask any compliance question in plain language and get instant, accurate answers backed by RBI circulars.',
  },
  {
    icon: '🗺️',
    title: 'Rule Visualization',
    desc: 'Explore the interconnected web of RBI regulations through an interactive force-directed graph.',
  },
  {
    icon: '📤',
    title: 'Circular Ingestion',
    desc: 'Upload new RBI PDFs and the system extracts, classifies, and indexes rules automatically.',
  },
  {
    icon: '',
    title: 'Compliance Checker',
    desc: 'Validate your operational data against current regulations and get detailed violation reports.',
  },
];

export default function LandingPage({ onStart }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animId;
    let particles = [];

    const resize = () => {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    for (let i = 0; i < 60; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.3,
        dx: (Math.random() - 0.5) * 0.3,
        dy: (Math.random() - 0.5) * 0.3,
        opacity: Math.random() * 0.5 + 0.1,
      });
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(200, 168, 75, ${p.opacity})`;
        ctx.fill();
        p.x += p.dx;
        p.y += p.dy;
        if (p.x < 0 || p.x > canvas.width)  p.dx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.dy *= -1;
      });

      // Draw faint connecting lines
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const d  = Math.sqrt(dx * dx + dy * dy);
          if (d < 120) {
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.strokeStyle = `rgba(200, 168, 75, ${0.06 * (1 - d / 120)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      animId = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return (
    <div className="landing">
      <canvas ref={canvasRef} className="landing-canvas" />

      {/* Header bar */}
      <header className="landing-header">
        <div className="landing-logo">
          <span className="logo-emblem">₹</span>
          <span className="logo-text">RBI Circular Assistant</span>
        </div>
        <div className="landing-badge">v2.0 </div>
      </header>

      {/* Hero */}
      <main className="landing-hero">
        <div className="hero-eyebrow">Reserve Bank of India</div>
        <h1 className="hero-title">
          Compliance <em>Intelligence</em>
          <br />for Financial Institutions
        </h1>
        <p className="hero-subtitle">
          Decode complex RBI circulars, visualize regulatory relationships,
          and validate operational data — all in one unified platform.
        </p>

        <button className="hero-cta" onClick={onStart}>
          <span>Open Dashboard</span>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M5 12h14M12 5l7 7-7 7"/>
          </svg>
        </button>

      </main>

      {/* Feature cards */}
      <section className="landing-features">
        {FEATURES.map((f, i) => (
          <div className="feature-card" key={i} style={{ animationDelay: `${i * 0.1 + 0.3}s` }}>
            <div className="feature-icon">{f.icon}</div>
            <h3 className="feature-title">{f.title}</h3>
            <p className="feature-desc">{f.desc}</p>
          </div>
        ))}
      </section>

      {/* Bottom strip */}
      <footer className="landing-footer">
        <span>© 2025 RBI Compliance System</span>
        <span className="footer-sep">·</span>
        <span>For authorized bank personnel only</span>
      </footer>
    </div>
  );
}
