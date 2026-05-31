const bcrypt = require("bcrypt")
const User = require("../models/User")

function buildUserResponse(user) {
  if (!user) {
    return null;
  }

  const plain = typeof user.toObject === "function" ? user.toObject() : user;

  delete plain.passwordHash;

  return plain;
}

exports.register = async (req, res) => {
  try {
    const {
      email,
      password,
      name = "",
      role = "",
      location = "",
      yearsExperience = 0,
      skills = [],
      experienceLevel = "junior"
    } = req.body

    // hash password
    const passwordHash = await bcrypt.hash(password, 10)

    const user = await User.create({
      email,
      passwordHash,
      name: name || email?.split("@")[0] || "",
      role,
      location,
      yearsExperience,
      skills: Array.isArray(skills) ? skills : [],
      experienceLevel
    })

    res.json(buildUserResponse(user))

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
      user: buildUserResponse(user)
    })

  } catch (error) {
    console.error(error)
    res.status(500).json({ error: "Server error" })
  }
}

exports.changePassword = async (req, res) => {
  try {
    const userId = req.user?.userId;
    const { currentPassword, newPassword } = req.body || {};

    if (!userId) {
      return res.status(401).json({ error: "Unauthorized" });
    }

    if (!currentPassword || !newPassword) {
      return res.status(400).json({ error: "currentPassword and newPassword are required" });
    }

    const user = await User.findById(userId);

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    const isMatch = await bcrypt.compare(currentPassword, user.passwordHash);

    if (!isMatch) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    user.passwordHash = await bcrypt.hash(newPassword, 10);
    await user.save();

    return res.json({ success: true });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: "Server error" });
  }
};

exports.resetPassword = async (req, res) => {
  try {
    const { email, newPassword } = req.body || {};

    if (!email || !newPassword) {
      return res.status(400).json({ error: "email and newPassword are required" });
    }

    const user = await User.findOne({ email });

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    user.passwordHash = await bcrypt.hash(newPassword, 10);
    await user.save();

    return res.json({ success: true });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: "Server error" });
  }
};

exports.logout = async (_req, res) => {
  return res.json({ success: true });
};