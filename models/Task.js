const mongoose = require("mongoose");

const taskSchema = new mongoose.Schema(
  {
    type: {
      type: String,
      required: true,
    },
    payload: {
      type: Object,
    },
    status: {
      type: String,
      enum: ["pending", "running", "completed", "failed"],
      default: "pending",
    },
    attempts: {
      type: Number,
      default: 0,
    },
  },
  { timestamps: true }
);

module.exports = mongoose.model("Task", taskSchema);