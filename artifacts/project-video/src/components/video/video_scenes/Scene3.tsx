import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';

export function Scene3() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 500),
      setTimeout(() => setPhase(2), 1000),
      setTimeout(() => setPhase(3), 1500),
    ];
    return () => timers.forEach(t => clearTimeout(t));
  }, []);

  return (
    <motion.div 
      className="absolute inset-0 flex flex-col items-center justify-center p-20 z-10"
      initial={{ scale: 1.2, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ y: '-100%', opacity: 0 }}
      transition={{ duration: 0.8 }}
    >
      <motion.h2 
        className="text-[4vw] font-display font-bold text-text-primary text-center mb-12"
      >
        Signal <span className="text-accent">Intelligence</span>
      </motion.h2>

      <div className="flex gap-8 w-full max-w-5xl">
        {[
          { title: "Quality Scoring", val: "94/100", color: "text-success", phase: 1 },
          { title: "Risk Gates", val: "PASSED", color: "text-primary", phase: 2 },
          { title: "Explainability", val: "LOGGED", color: "text-secondary", phase: 3 }
        ].map((item, i) => (
          <motion.div 
            key={i}
            className="flex-1 bg-bg-muted/80 backdrop-blur-md border border-white/10 rounded-2xl p-8 flex flex-col items-center justify-center"
            initial={{ y: 50, opacity: 0 }}
            animate={phase >= item.phase ? { y: 0, opacity: 1 } : { y: 50, opacity: 0 }}
            transition={{ type: "spring", bounce: 0.4 }}
          >
            <div className="text-[1.2vw] font-mono text-text-secondary mb-4 uppercase tracking-widest">{item.title}</div>
            <div className={`text-[2.5vw] font-display font-bold ${item.color}`}>{item.val}</div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
