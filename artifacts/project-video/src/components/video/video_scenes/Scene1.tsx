import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';

export function Scene1() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 300),
      setTimeout(() => setPhase(2), 1200),
    ];
    return () => timers.forEach(t => clearTimeout(t));
  }, []);

  return (
    <motion.div 
      className="absolute inset-0 flex flex-col items-center justify-center z-10"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ scale: 2, opacity: 0, filter: 'blur(10px)' }}
      transition={{ duration: 0.8 }}
    >
      <div className="text-center">
        <motion.h1 
          className="text-[6vw] font-display font-bold text-text-primary uppercase tracking-tight leading-none mb-4"
          initial={{ y: 50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        >
          NSE Trading
          <br />
          <span className="text-primary">Dashboard</span>
        </motion.h1>
        
        <motion.p 
          className="text-[2vw] font-body text-text-secondary"
          initial={{ opacity: 0, y: 20 }}
          animate={phase >= 1 ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
          transition={{ duration: 0.6 }}
        >
          Algorithmic Paper-Trading Research Platform
        </motion.p>
      </div>

      {phase >= 2 && (
        <motion.div 
          className="absolute bottom-10"
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <div className="px-6 py-3 rounded-full border border-primary/30 bg-primary/10">
            <span className="font-mono text-primary text-[1.2vw]">Zerodha Kite Connect Integrated</span>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}
