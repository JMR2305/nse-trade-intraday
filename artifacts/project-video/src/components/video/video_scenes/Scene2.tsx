import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';

export function Scene2() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 400),
      setTimeout(() => setPhase(2), 1500),
    ];
    return () => timers.forEach(t => clearTimeout(t));
  }, []);

  return (
    <motion.div 
      className="absolute inset-0 flex items-center p-20 z-10"
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '-100%', opacity: 0 }}
      transition={{ type: "spring", stiffness: 100, damping: 20 }}
    >
      <div className="w-1/2">
        <motion.h2 
          className="text-[4vw] font-display font-bold text-text-primary leading-tight"
        >
          Live Market
          <br />
          <span className="text-secondary">Scanning</span>
        </motion.h2>
        
        <motion.p 
          className="text-[1.5vw] font-body text-text-secondary mt-6 max-w-md"
          initial={{ opacity: 0 }}
          animate={phase >= 1 ? { opacity: 1 } : { opacity: 0 }}
        >
          Continuous NSE stock scans for MACD and technical signals using read-only live data.
        </motion.p>
      </div>

      <div className="w-1/2 relative h-full flex items-center justify-center">
        <motion.div 
          className="w-full aspect-video border border-secondary/30 rounded-xl bg-bg-muted/50 p-6 flex flex-col relative overflow-hidden"
          initial={{ scale: 0.8, opacity: 0, rotateY: 30 }}
          animate={phase >= 1 ? { scale: 1, opacity: 1, rotateY: 0 } : { scale: 0.8, opacity: 0, rotateY: 30 }}
          transition={{ duration: 0.8 }}
          style={{ perspective: 1000 }}
        >
          <div className="flex gap-2 mb-4">
            <div className="w-3 h-3 rounded-full bg-error" />
            <div className="w-3 h-3 rounded-full bg-warning" />
            <div className="w-3 h-3 rounded-full bg-success" />
          </div>
          
          <div className="flex-1 border-b border-secondary/20 relative">
            <motion.svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
              <motion.path 
                d="M 0 80 Q 20 80, 40 40 T 80 20 T 100 10" 
                fill="none" 
                stroke="var(--color-secondary)" 
                strokeWidth="2"
                initial={{ pathLength: 0 }}
                animate={phase >= 2 ? { pathLength: 1 } : { pathLength: 0 }}
                transition={{ duration: 1.5, ease: "easeInOut" }}
              />
              <motion.path 
                d="M 0 90 Q 20 90, 40 50 T 80 30 T 100 15" 
                fill="none" 
                stroke="var(--color-primary)" 
                strokeWidth="1"
                initial={{ pathLength: 0 }}
                animate={phase >= 2 ? { pathLength: 1 } : { pathLength: 0 }}
                transition={{ duration: 1.5, ease: "easeInOut", delay: 0.2 }}
              />
            </motion.svg>
          </div>
          
          <div className="mt-4 flex justify-between font-mono text-[1vw] text-secondary">
            <span>MACD Crossover detected</span>
            <span>RELIANCE</span>
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
}
