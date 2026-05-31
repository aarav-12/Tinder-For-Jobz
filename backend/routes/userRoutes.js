const express = require("express")
const router = express.Router()

const authMiddleware = require("../middleware/authMiddleware")
const { getMe, getResume, updateMe, getSavedJobs, getAppliedJobs } = require("../controllers/userController")

router.get("/me", authMiddleware, getMe)
router.put("/me", authMiddleware, updateMe)
router.patch("/me", authMiddleware, updateMe)
router.get("/me/resume", authMiddleware, getResume)
router.get("/me/saved-jobs", authMiddleware, getSavedJobs)
router.get("/me/applied-jobs", authMiddleware, getAppliedJobs)

module.exports = router