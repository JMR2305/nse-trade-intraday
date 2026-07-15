import { Router, type IRouter } from "express";
import healthRouter from "./health";
import tradingRouter from "./trading";
import streamRouter from "./stream";
import phase12Router from "./phase12";
import phase13Router from "./phase13";
import phase14Router from "./phase14";
import phase15Router from "./phase15";
import phase16Router from "./phase16";
import phase17Router from "./phase17";
import phase18Router from "./phase18";
import kiteRouter from "./kite";

const router: IRouter = Router();

router.use(healthRouter);
router.use(streamRouter);
router.use(phase12Router);
router.use(phase13Router);
router.use(phase14Router);
router.use(phase15Router);
router.use(phase16Router);
router.use(phase17Router);
router.use(phase18Router);
router.use(kiteRouter);
router.use(tradingRouter);

export default router;
