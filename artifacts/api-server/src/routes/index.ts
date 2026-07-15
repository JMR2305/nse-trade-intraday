import { Router, type IRouter } from "express";
import healthRouter from "./health";
import tradingRouter from "./trading";
import streamRouter from "./stream";
import phase12Router from "./phase12";
import phase13Router from "./phase13";
import phase14Router from "./phase14";
import phase15Router from "./phase15";

const router: IRouter = Router();

router.use(healthRouter);
router.use(streamRouter);
router.use(phase12Router);
router.use(phase13Router);
router.use(phase14Router);
router.use(phase15Router);
router.use(tradingRouter);

export default router;
