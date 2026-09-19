import { Router, type IRouter } from "express";
import healthRouter from "./health";
import commissioningKiteAuthRouter from "./commissioningKiteAuth";

const router: IRouter = Router();

router.use(healthRouter);
// Task978ZI: commissioning mode additionally exposes ONLY the minimal Kite
// authentication routes (GET /api/kite/login, GET /api/kite/callback) needed
// to establish the durable read-only provider session. The full Kite router
// and every other application route remain normal-mode-only.
router.use(commissioningKiteAuthRouter);

export default router;
