"use client";

import Image from "next/image";
import Link from "next/link";
import { motion } from "motion/react";
import { ArrowDown, ArrowUpRight, Check, Microphone, Phone, Quotes, Train, Waveform } from "@phosphor-icons/react";

const phrases = [
  { copy: "Kal subah 8 baje", className: "phrase phrase--one" },
  { copy: "घर से स्टेशन", className: "phrase phrase--two" },
  { copy: "Book kar do", className: "phrase phrase--three" },
  { copy: "Abhi hospital jaana hai", className: "phrase phrase--four" },
];

function Brand() {
  return <Link className="brand" href="/" aria-label="BoloRide home"><span className="brand-mark"><Waveform weight="bold" /></span><span>BoloRide</span></Link>;
}

export default function Home() {
  return <main className="aura-site">
    <nav className="aura-nav" aria-label="Primary navigation">
      <Brand />
      <div className="aura-nav-links"><a href="#why">Why BoloRide</a><a href="#how">How it works</a><a href="#language">Indian speech</a></div>
      <Link className="button button--ink" href="/demo">Try the call <ArrowUpRight weight="bold" /></Link>
    </nav>

    <section className="aura-hero">
      <div className="hero-intro">
        <p className="mono-kicker"><span />VOICE-FIRST MOBILITY · INDIA</p>
        <h1>A cab ride,<br />without the <em>app dance.</em></h1>
        <p className="hero-lede">Call. Say where you need to go. BoloRide handles the rest through a natural conversation in Hindi, Hinglish, or English.</p>
        <div className="hero-ctas"><Link className="button button--red" href="/demo"><Phone weight="fill" /> Call BoloRide</Link><a className="text-link" href="#how">See how it flows <ArrowDown /></a></div>
        <div className="hero-proof"><span className="proof-avatars"><i>हि</i><i>EN</i><i>H+</i></span><p><strong>Speak normally.</strong><br />No commands to memorise.</p></div>
      </div>

      <div className="hero-visual">
        <div className="hero-photo"><Image src="/assets/boloride-station-call.jpg" alt="An older Indian traveller booking a ride by phone outside a railway station" fill priority sizes="(max-width: 900px) 100vw, 52vw" /></div>
        <div className="route-ticket"><span><Train weight="fill" /></span><div><small>FAMILIAR ROUTE</small><strong>Home → Station</strong></div><b>08:00</b></div>
        <div className="live-pill"><i /> READY TO LISTEN</div>
        <p className="photo-note">Designed for the journeys people already know.</p>
      </div>
    </section>

    <section className="phrase-lab" id="language">
      <div className="section-heading"><p className="mono-kicker"><span />TALK LIKE YOURSELF</p><h2>Indian speech is not an edge case.</h2><p>Drag the phrases. Mix the language. BoloRide is built for the way real conversations move.</p></div>
      <div className="phrase-canvas">
        <div className="canvas-grid" aria-hidden="true" />
        <p className="canvas-hint"><Microphone /> GRAB · MOVE · SPEAK</p>
        {phrases.map(phrase => <motion.div key={phrase.copy} className={phrase.className} drag dragConstraints={{ left: -80, right: 80, top: -55, bottom: 55 }} dragElastic={.12} whileDrag={{ scale: 1.06, zIndex: 10 }}>{phrase.copy}<span>↗</span></motion.div>)}
        <div className="sound-track" aria-hidden="true">{Array.from({ length: 42 }, (_, index) => <i key={index} style={{ height: `${16 + ((index * 17) % 52)}%` }} />)}</div>
        <div className="language-score"><small>LANGUAGE MODE</small><strong>Hinglish</strong><b>LIVE</b></div>
      </div>
    </section>

    <section className="why-grid" id="why">
      <article className="why-story"><p className="mono-kicker"><span />WHY IT EXISTS</p><h2>The journey is simple.<br />The interface should be too.</h2><p>Maps, pins, fare screens and confirmation steps feel normal—until they become the reason someone needs help booking a ride.</p><blockquote><Quotes weight="fill" /> “I know where I need to go. I just need a simpler way to say it.”</blockquote></article>
      <article className="why-stat"><span>01</span><strong>One familiar action</strong><p>Make a phone call.</p><Phone weight="thin" /></article>
      <article className="why-stat why-stat--purple"><span>03</span><strong>Languages together</strong><p>Hindi · Hinglish · English</p><Waveform weight="thin" /></article>
      <article className="why-image"><Image src="/assets/boloride-station-call.jpg" alt="An Indian railway station journey" fill sizes="(max-width: 900px) 100vw, 40vw" /></article>
    </section>

    <section className="flow-section" id="how">
      <div className="section-heading section-heading--row"><div><p className="mono-kicker"><span />THE CALL FLOW</p><h2>From “hello” to<br />ride confirmed.</h2></div><p>Important details are confirmed once. Fares, vehicles, and booking state come from reliable services—not an AI guess.</p></div>
      <div className="flow-list">
        <article><span>01</span><div className="flow-icon"><Phone /></div><h3>Call</h3><p>Dial BoloRide from a phone you already know.</p><b>1800-258-2334</b></article>
        <article><span>02</span><div className="flow-icon"><Microphone /></div><h3>Say it naturally</h3><p>“Kal morning station ke liye cab book kar do.”</p><b>NO FIXED COMMANDS</b></article>
        <article><span>03</span><div className="flow-icon"><Check /></div><h3>Confirm and go</h3><p>Review the route, fare, vehicle, and pickup time.</p><b>ONE CLEAR SUMMARY</b></article>
      </div>
    </section>

    <section className="final-cta">
      <p className="mono-kicker"><span />LIVE PRODUCT PREVIEW</p><h2>Your next ride starts<br />with a sentence.</h2><Link className="button button--red" href="/demo">Open the phone demo <ArrowUpRight weight="bold" /></Link><p className="final-note">Experimental prototype · simulated fleet · live voice connection</p>
      <div className="orbit-word" aria-hidden="true">BOLO · RIDE · BOLO · RIDE ·</div>
    </section>

    <footer><Brand /><p>Conversation over navigation.</p><span>© 2026 BoloRide · Prototype</span></footer>
  </main>;
}
