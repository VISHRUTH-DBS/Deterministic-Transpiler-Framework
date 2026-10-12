interface Student {
    name: string;
    marks: number;
}

type Grade = string;

function calculateGrade(marks: number): Grade {
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

const studentName: string = "Rahul";
const studentMarks: number = 85;

const grade: Grade = calculateGrade(studentMarks);

console.log(studentName);
console.log(grade);
