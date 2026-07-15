import { motion } from 'framer-motion';

export function Scene5() {
  return (
    <motion.div 
      className="absolute inset-0 flex flex-col items-center justify-center p-20 z-10 bg-bg-dark"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 1 }}
    >
      <motion.div 
        className="text-center"
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.5, duration: 0.8 }}
      >
        <div className="inline-block px-8 py-4 bg-success/20 border border-success/50 rounded-2xl mb-8">
          <p className="font-mono text-success text-[1.5vw] uppercase tracking-widest">
            Simulated Capital
          </p>
          <p className="font-display font-bold text-success text-[4vw] mt-2">
            ₹5,000
          </p>
        </div>
        
        <h2 className="text-[3vw] font-display font-bold text-text-primary">
          Research-Only Paper Trading
        </h2>
        <p className="text-[1.5vw] font-body text-text-secondary mt-4">
          No real orders ever placed. Production app: Zerodha Trading Assistant.
        </p>
      </motion.div>
    </motion.div>
  );
}
