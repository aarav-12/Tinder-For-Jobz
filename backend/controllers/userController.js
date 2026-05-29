const User = require("../models/User")
const { getUserInterestEntries, getUserInterests } = require("../services/interestService")

exports.getMe = async (req, res) => {
  try {

    const user = await User.findById(req.user.userId).select("-passwordHash")

    res.json(user)

  } catch (error) {
    res.status(500).json({ error: "Server error" })
  }
}

exports.getInterests = async (req, res) => {
  try {
    const userId = req.user.userId
    const interests = await getUserInterests(userId)

    res.json(interests)
  } catch (error) {
    res.status(500).json({ error: "Server error" })
  }
}

exports.getInterestRows = async (req, res) => {
  try {
    const userId = req.user.userId
    const interests = await getUserInterestEntries(userId)

    res.json(interests)
  } catch (error) {
    res.status(500).json({ error: "Server error" })
  }
}