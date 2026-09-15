import Link from "next/link";

export default function Home() {
  return <main className="site-shell landing-page">
    <div className="night-city" aria-hidden="true"><i/><i/><i/><i/><i/><i/></div>
    <nav className="site-nav" aria-label="Primary navigation">
      <Link className="nav-brand" href="/">
  <span className="brand-icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="none">
      <path
        d="M5 16V10.8C5 10.3 5.15 9.82 5.43 9.4L7.35 6.52C7.63 6.1 8.1 5.85 8.6 5.85H15.4C15.9 5.85 16.37 6.1 16.65 6.52L18.57 9.4C18.85 9.82 19 10.3 19 10.8V16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      <path
        d="M6 11H18"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />

      <path
        d="M8 8.5H16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />

      <circle cx="7.5" cy="15.5" r="1.5" fill="currentColor" />
      <circle cx="16.5" cy="15.5" r="1.5" fill="currentColor" />
    </svg>
  </span>

  <span className="brand-name">
    <span>Bolo</span><span className="accent">Ride</span>
  </span>
</Link>
      <div className="nav-links"><a href="#how-it-works">How it Works</a><a href="#features">The experience</a></div>
      <Link className="nav-demo-link" href="/demo">Try Live Demo <span>↗</span></Link>
    </nav>
    <section className="landing-hero">
      <div className="hero-copy"><p className="eyebrow"><i/> A simpler way to get there</p>
        <h1>Book a ride,<br/><em>just by speaking.</em></h1>
        <p className="hero-description">A voice-first ride experience in Hindi, Hinglish, and English. Say where you want to go. Let the conversation guide the journey.</p>
        <div className="hero-actions"><Link className="primary-cta" href="/demo">Try Live Demo <span>→</span></Link><a href="#how-it-works">Explore the experience ↓</a></div>
        <p className="preview-note">Explore an interactive phone preview. Calls are simulated.</p>
      </div>
      <div className="journey-art" aria-hidden="true"><div className="journey-halo"/><svg viewBox="0 0 520 550" fill="none"><path d="M-30 490Q330 380 170 220T430 25" stroke="#42f5c5" strokeWidth="2"/><path d="M30 570Q410 410 225 215T490 10" stroke="#20b9c5" strokeOpacity=".2"/><circle cx="209" cy="348" r="10" fill="#42f5c5"/><circle cx="209" cy="348" r="25" stroke="#42f5c5" strokeOpacity=".4"/><circle cx="325" cy="45" r="6" fill="#42f5c5"/></svg><span className="journey-word">Just say<br/><em>where.</em></span></div>
    </section>
    <section className="landing-details" id="how-it-works"><p className="eyebrow">A familiar phone. A new conversation.</p><div id="features"><article><span>01</span><h2>Open the phone</h2><p>Step into the preview and unlock a familiar personal phone.</p></article><article><span>02</span><h2>Call BoloRide</h2><p>Find BoloRide in Recents or try the keypad.</p></article><article><span>03</span><h2>Explore the call</h2><p>Hear the caller tune and explore the simulated call controls.</p></article></div></section>
  </main>;
}
