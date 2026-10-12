function calculateGrade(marks) {
  if (marks >= 90) {
    return "A";
  } else if (marks >= 75) {
    return "B";
  } else if (marks >= 50) {
    return "C";
  } else {
    return "F";
  }
}

const studentName = "Rahul";
const studentMarks = 85;
const grade = calculateGrade(studentMarks);
console.log(studentName);
console.log(grade);
