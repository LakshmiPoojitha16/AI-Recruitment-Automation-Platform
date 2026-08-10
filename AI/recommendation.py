from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def recommend_jobs(resume_text, jobs):

    recommendations = []

    for job in jobs:

        job_text = job.get("description", "")

        vectorizer = CountVectorizer().fit_transform(
            [resume_text, job_text]
        )

        vectors = vectorizer.toarray()

        similarity = cosine_similarity(vectors)

        score = round(similarity[0][1] * 100, 2)

        job["recommendation_score"] = score

        recommendations.append(job)

    recommendations.sort(
        key=lambda x: x["recommendation_score"],
        reverse=True
    )

    return recommendations