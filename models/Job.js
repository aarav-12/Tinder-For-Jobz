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

  location: {
    type: String,
    default: "N/A",
  },

  applyUrl: {
    type: String,
    required: true,
  },

  greenhouseJobId: {
    type: Number,
    unique: true, // 🔥 prevents duplicates
  },

  // your original fields (keep them)
  requiredSkills: {
    type: [String],
    default: [],
  },

  minExperience: {
    type: Number,
    default: 0,
  },

  createdAt: {
    type: Date,
    default: Date.now,
  },
});

module.exports = mongoose.model("Job", jobSchema);