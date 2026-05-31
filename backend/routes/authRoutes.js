const express = require("express")
const router = express.Router()

const authMiddleware = require("../middleware/authMiddleware")
const { register, login, logout, changePassword, resetPassword } = require("../controllers/authController")
router.post("/register", register)
router.post("/login", login)
router.post("/logout", logout)
router.post("/reset-password", resetPassword)
router.put("/change-password", authMiddleware, changePassword)
module.exports = router