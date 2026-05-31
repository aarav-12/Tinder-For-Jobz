const mongoose = require("mongoose")

const userSchema = new mongoose.Schema({
  email: {
    type: String,
    required: true,
    unique: true
  },

  name: {
    type: String,
    default: ""
  },

  passwordHash: {
    type: String,
    required: true
  },

  role: {
    type: String,
    default: ""
  },

  location: {
    type: String,
    default: ""
  },

  yearsExperience: {
    type: Number,
    default: 0
  },

  skills: {
    type: [String],
    default: []
  },

  experienceLevel: {
    type: String,
    default: "junior"
  },

  resume: {
    filename: {
      type: String,
      default: ""
    },
    contentType: {
      type: String,
      default: ""
    },
    analyzedAt: {
      type: Date,
      default: null
    },
    analysis: {
      type: mongoose.Schema.Types.Mixed,
      default: null
    }
  },

  createdAt: {
    type: Date,
    default: Date.now
  }
})

module.exports = mongoose.model("User", userSchema)