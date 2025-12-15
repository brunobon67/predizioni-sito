export async function handler() {
  const res = await fetch(
    "https://predizioni-sito.onrender.com/api/admin/update-matches",
    {
      method: "POST",
      headers: {
        "X-Admin-Token": process.env.ADMIN_TOKEN
      }
    }
  );

  return {
    statusCode: res.status,
    body: await res.text()
  };
}
