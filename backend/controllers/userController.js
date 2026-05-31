const User = require("../models/User")
const Behavior = require("../models/Behavior")
const { getUserInterestEntries, getUserInterests } = require("../services/interestService")

function sanitizeUser(user) {
  if (!user) {
    return null;
  }

  const plain = typeof user.toObject === "function" ? user.toObject() : user;
  delete plain.passwordHash;
  return plain;
}

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

exports.updateMe = async (req, res) => {
  try {
    const updates = {};
    const allowedFields = ["name", "role", "location", "yearsExperience", "skills", "experienceLevel"];

    for (const field of allowedFields) {
      if (Object.prototype.hasOwnProperty.call(req.body || {}, field)) {
        updates[field] = req.body[field];
      }
    }

    if (Array.isArray(updates.skills)) {
      updates.skills = updates.skills.filter((skill) => typeof skill === "string" && skill.trim());
    }

    const user = await User.findByIdAndUpdate(
      req.user.userId,
      { $set: updates },
      { new: true }
    ).select("-passwordHash");

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    res.json(sanitizeUser(user));
  } catch (error) {
    res.status(500).json({ error: "Server error" });
  }
};

exports.getResume = async (req, res) => {
  try {
    const user = await User.findById(req.user.userId).select("resume");

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    res.json(user.resume || null);
  } catch (error) {
    res.status(500).json({ error: "Server error" });
  }
};

exports.getSavedJobs = async (req, res) => {
  try {
    const savedBehaviors = await Behavior.find({
      userId: req.user.userId,
      action: "save",
    })
      .sort({ createdAt: -1 })
      .populate("postId")
      .lean();

    const jobs = savedBehaviors.map((behavior) => behavior.postId).filter(Boolean);

    res.json({ jobs, behaviors: savedBehaviors });
  } catch (error) {
    res.status(500).json({ error: "Server error" });
  }
};

exports.getAppliedJobs = async (req, res) => {
  try {
    const appliedBehaviors = await Behavior.find({
      userId: req.user.userId,
      action: "apply",
    })
      .sort({ createdAt: -1 })
      .populate("postId")
      .lean();

    const jobs = appliedBehaviors.map((behavior) => behavior.postId).filter(Boolean);

    res.json({ jobs, behaviors: appliedBehaviors });
  } catch (error) {
    res.status(500).json({ error: "Server error" });
  }
};

exports.getInterestRows = async (req, res) => {
  try {
    const userId = req.user.userId
    const interests = await getUserInterestEntries(userId)

    res.json(interests)
  } catch (error) {
    res.status(500).json({ error: "Server error" })
  }
}