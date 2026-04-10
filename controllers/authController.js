const bcrypt = require("bcrypt")
const User = require("../models/User")

exports.register = async (req, res) => {
  try {

    const { email, password } = req.body

    // hash password
    const passwordHash = await bcrypt.hash(password, 10)

    const user = await User.create({
      email,
      passwordHash,
      skills: [],
      experienceLevel: "junior"
    })

    res.json(user)

  } catch (error) {
    console.error(error)
    res.status(500).json({ error: "Server error" })
  }
}

const jwt = require("jsonwebtoken")

exports.login = async (req, res) => {
  try {

    const { email, password } = req.body

    const user = await User.findOne({ email })

    if (!user) {
      return res.status(401).json({ error: "Invalid credentials" })
    }

    const isMatch = await bcrypt.compare(password, user.passwordHash)

    if (!isMatch) {
      return res.status(401).json({ error: "Invalid credentials" })
    }

    const token = jwt.sign(
      { userId: user._id },
      process.env.JWT_SECRET,
      { expiresIn: "7d" }
    )

    res.json({
      token,
      user: {
        _id: user._id,
        email: user.email,
        skills: user.skills,
        experienceLevel: user.experienceLevel
      }
    })

  } catch (error) {
    console.error(error)
    res.status(500).json({ error: "Server error" })
  }
}