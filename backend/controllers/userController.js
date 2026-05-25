const User = require("../models/User")

exports.getMe = async (req, res) => {
  try {

    const user = await User.findById(req.user.userId).select("-passwordHash")

    res.json(user)

  } catch (error) {
    res.status(500).json({ error: "Server error" })
  }
}