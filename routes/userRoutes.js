const express = require("express")
const router = express.Router()

const authMiddleware = require("../middleware/authMiddleware")
const { getMe } = require("../controllers/userController")

router.get("/me", authMiddleware, getMe)

module.exports = router