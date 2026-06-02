"use client";
import { motion } from "framer-motion";

export default function GradientBackground() {
  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden" style={{ zIndex: 0 }}>
      {/* Primary violet blob */}
      <motion.div
        animate={{ x: [0, 30, 0], y: [0, -20, 0], scale: [1, 1.1, 1] }}
        transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        className="absolute top-[-20%] left-[-10%] w-[700px] h-[700px] rounded-full"
        style={{ background: "radial-gradient(circle, rgba(139,92,246,0.12) 0%, transparent 70%)" }}
      />
      {/* Indigo blob */}
      <motion.div
        animate={{ x: [0, -40, 0], y: [0, 30, 0], scale: [1, 0.9, 1] }}
        transition={{ duration: 22, repeat: Infinity, ease: "easeInOut", delay: 4 }}
        className="absolute top-[30%] right-[-15%] w-[600px] h-[600px] rounded-full"
        style={{ background: "radial-gradient(circle, rgba(99,102,241,0.10) 0%, transparent 70%)" }}
      />
      {/* Purple accent blob */}
      <motion.div
        animate={{ x: [0, 20, 0], y: [0, 40, 0], scale: [1, 1.15, 1] }}
        transition={{ duration: 26, repeat: Infinity, ease: "easeInOut", delay: 8 }}
        className="absolute bottom-[-10%] left-[30%] w-[500px] h-[500px] rounded-full"
        style={{ background: "radial-gradient(circle, rgba(168,85,247,0.08) 0%, transparent 70%)" }}
      />
      {/* Grid overlay */}
      <div className="absolute inset-0"
        style={{ backgroundImage: "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0)", backgroundSize: "40px 40px" }}
      />
      {/* Top gradient fade */}
      <div className="absolute inset-x-0 top-0 h-32"
        style={{ background: "linear-gradient(to bottom, #050816, transparent)" }}
      />
    </div>
  );
}
