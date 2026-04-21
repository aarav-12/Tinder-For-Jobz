const mongoose = require("mongoose");

const jobSchema = new mongoose.Schema({
  title: {
    type: String,
    required: true,
  },

  company: {
    type: String,
    required: true,
  },

  source: {
    type: String,
    enum: ["greenhouse", "lever"],
    required: true,
  },

  location: {
    type: String,
    default: "N/A",
  },

  applyUrl: {
    type: String,
    required: true,
  },

  externalId: {
    type: String,
    required: true,
    unique: true, // 🔥 deduplication backbone
    index: true,
  },

  greenhouseJobId: {
    type: Number,
  },

  // existing fields
  requiredSkills: {
    type: [String],
    default: [],
  },

  minExperience: {
    type: Number,
    default: 0,
  },

  // 🔥 NEW — lifecycle management
  isActive: {
    type: Boolean,
    default: true,
  },

  lastFetchedAt: {
    type: Date,
    default: Date.now,
  },

  createdAt: {
    type: Date,
    default: Date.now,
  },

  updatedAt: {
    type: Date,
    default: Date.now,
  },
});

jobSchema.index({ isActive: 1, minExperience: 1, createdAt: -1 });

module.exports = mongoose.model("Job", jobSchema);