/**
 * Logo.tsx — backward-compatible re-export of ApexQuant AI brand components.
 *
 * Existing code that imports { Logo } or { ApexSymbol } from this path
 * continues to work unchanged. New code should import from BrandLogo or
 * BrandMark directly.
 */
export { BrandLogo as Logo } from "./BrandLogo";
export { BrandMark as ApexSymbol } from "./BrandMark";
// Also re-export the full brand kit for convenience
export { BrandLogo } from "./BrandLogo";
export { BrandMark } from "./BrandMark";
export { BrandHeader } from "./BrandHeader";
export { PaperTradingBadge } from "./PaperTradingBadge";
