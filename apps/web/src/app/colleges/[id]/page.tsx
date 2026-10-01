import { CollegeDetailClient } from "./CollegeDetailClient";

export default async function CollegeDetailPage(props: PageProps<"/colleges/[id]">) {
  const { id } = await props.params;
  return <CollegeDetailClient collegeId={Number(id)} />;
}
