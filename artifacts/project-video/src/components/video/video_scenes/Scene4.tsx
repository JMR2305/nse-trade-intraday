import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';

export function Scene4() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 600),
    ];
    return () => timers.forEach(t => clearTimeout(t));
  }, []);

  return (
    <motion.div 
      className="absolute inset-0 flex items-center p-20 z-10"
      initial={{ opacity: 0, rotateX: 90 }}
      animate={{ opacity: 1, rotateX: 0 }}
      exit={{ scale: 0.5, opacity: 0 }}
      transition={{ duration: 0.8 }}
      style={{ transformOrigin: 'bottom' }}
    >
      <div className="w-1/2">
        <motion.div
          className="w-full aspect-square border-2 border-dashed border-primary/30 rounded-full flex items-center justify-center relative"
          animate={{ rotate: 360 }}
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        >
          <motion.div className="w-3/4 h-3/4 border border-secondary/50 rounded-full flex items-center justify-center relative"
            animate={{ rotate: -360 }}
            transition={{ duration: 15, repeat: Infinity, ease: "linear" }}>
             <motion.div className="w-1/2 h-1/2 bg-accent/20 rounded-full" />
          </motion.div>
        </motion.div>
      </div>

      <div className="w-1/2 pl-12">
        <motion.h2 
          className="text-[3.5vw] font-display font-bold text-text-primary mb-6"
        >
          Validation & Learning
        </motion.h2>
        
        <ul className="space-y-6">
          {[
            "Backtesting Engines",
            "Walk-forward validation",
            "Strategy calibration loop"
          ].map((text, i) => (
            <motion.li 
              key={i}
              className="flex items-center text-[1.8vw] font-body text-text-secondary"
              initial={{ x: 50, opacity: 0 }}
              animate={phase >= 1 ? { x: 0, opacity: 1 } : { x: 50, opacity: 0 }}
              transition={{ delay: i * 0.2 }}
            >
              <div className="w-4 h-4 rounded-sm bg-primary mr-4" />
              {text}
            </motion.li>
          ))}
        </ul>
      </div>
    </motion.div>
  );
}
